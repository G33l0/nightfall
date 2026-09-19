"""Live metric collection with bounded memory.

The collector is fed a :class:`RequestResult` per completed request. It keeps:

* running counters (total / success / fail, status buckets, error buckets);
* a **reservoir sample** of latencies for whole-test percentiles with a fixed
  memory ceiling (spec section 15);
* per-second request buckets for the RPS graph and peak-RPS tracking;
* a small rolling deque of recent per-request events for the live user feed
  (spec section 16) so the terminal is never flooded.
"""
from __future__ import annotations

import random
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .models import ErrorKind, RequestResult

# Fixed ceilings -> memory stays flat no matter how long the test runs.
_RESERVOIR_SIZE = 100_000
_RECENT_EVENTS = 12
_RPS_HISTORY = 120          # seconds retained for the rolling graph
_LATENCY_WINDOW = 5_000     # recent latencies for the live latency graph


@dataclass(slots=True)
class LatencyStats:
    minimum: float = 0.0
    average: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    maximum: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "min_ms": round(self.minimum, 2),
            "avg_ms": round(self.average, 2),
            "p50_ms": round(self.p50, 2),
            "p90_ms": round(self.p90, 2),
            "p95_ms": round(self.p95, 2),
            "p99_ms": round(self.p99, 2),
            "max_ms": round(self.maximum, 2),
        }


@dataclass(slots=True)
class RecentEvent:
    user_id: int
    method: str
    path: str
    status: int
    latency_ms: float
    ok: bool


class MetricsCollector:
    """Aggregates request outcomes into live and final statistics."""

    def __init__(self, method: str = "GET", path: str = "/") -> None:
        self._method = method
        self._path = path

        self.total = 0
        self.success = 0
        self.failed = 0
        self.total_bytes = 0

        self.status_buckets: dict[str, int] = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
        self.status_codes: dict[int, int] = {}
        self.errors: dict[str, int] = {}

        # Whole-test latency: running aggregates + reservoir for percentiles.
        self._lat_min: Optional[float] = None
        self._lat_max: float = 0.0
        self._lat_sum: float = 0.0
        self._reservoir: list[float] = []
        self._seen = 0

        # Rolling windows.
        self._recent_latencies: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self.recent_events: deque[RecentEvent] = deque(maxlen=_RECENT_EVENTS)
        self._rps_buckets: dict[int, int] = {}
        self.peak_rps = 0.0

        self._start = time.monotonic()
        self._start_wall = time.time()
        self.active_users = 0
        self.peak_active_users = 0

    # -- lifecycle ---------------------------------------------------------
    def mark_start(self) -> None:
        self._start = time.monotonic()
        self._start_wall = time.time()

    def user_started(self) -> None:
        self.active_users += 1
        self.peak_active_users = max(self.peak_active_users, self.active_users)

    def user_finished(self) -> None:
        self.active_users = max(0, self.active_users - 1)

    @property
    def start_wall(self) -> float:
        return self._start_wall

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    # -- ingestion ---------------------------------------------------------
    def record(self, user_id: int, result: RequestResult) -> None:
        self.total += 1
        self.total_bytes += result.bytes_received

        if result.success:
            self.success += 1
        else:
            self.failed += 1

        # Status buckets / codes.
        if result.status > 0:
            code = result.status
            self.status_codes[code] = self.status_codes.get(code, 0) + 1
            bucket = f"{code // 100}xx"
            if bucket in self.status_buckets:
                self.status_buckets[bucket] += 1
            else:
                self.status_buckets["other"] += 1

        # Error buckets.
        if result.error is not None:
            key = result.error.value
            self.errors[key] = self.errors.get(key, 0) + 1

        # Latency aggregates (only meaningful for completed responses).
        lat = result.latency_ms
        self._lat_sum += lat
        self._lat_max = max(self._lat_max, lat)
        self._lat_min = lat if self._lat_min is None else min(self._lat_min, lat)
        self._recent_latencies.append(lat)
        self._reservoir_add(lat)

        # Per-second bucket for RPS graph.
        sec = int(self.elapsed())
        self._rps_buckets[sec] = self._rps_buckets.get(sec, 0) + 1
        self._trim_rps_buckets(sec)

        # Recent event feed.
        self.recent_events.append(
            RecentEvent(
                user_id=user_id,
                method=self._method,
                path=self._path,
                status=result.status,
                latency_ms=lat,
                ok=result.success,
            )
        )

    def _reservoir_add(self, value: float) -> None:
        self._seen += 1
        if len(self._reservoir) < _RESERVOIR_SIZE:
            self._reservoir.append(value)
        else:
            j = random.randint(0, self._seen - 1)
            if j < _RESERVOIR_SIZE:
                self._reservoir[j] = value

    def _trim_rps_buckets(self, current_sec: int) -> None:
        cutoff = current_sec - _RPS_HISTORY
        if cutoff < 0:
            return
        stale = [s for s in self._rps_buckets if s < cutoff]
        for s in stale:
            del self._rps_buckets[s]

    # -- derived / live ----------------------------------------------------
    def current_rps(self) -> float:
        """Requests observed in the last completed whole second."""
        sec = int(self.elapsed()) - 1
        if sec < 0:
            return float(self._rps_buckets.get(0, 0))
        return float(self._rps_buckets.get(sec, 0))

    def average_rps(self) -> float:
        elapsed = max(self.elapsed(), 1e-9)
        return self.total / elapsed

    def update_peak_rps(self) -> None:
        # Peak is measured over settled (past) buckets only.
        current_sec = int(self.elapsed())
        for sec, count in self._rps_buckets.items():
            if sec < current_sec:
                self.peak_rps = max(self.peak_rps, float(count))

    def rps_series(self, width: int = 30) -> list[int]:
        """The most recent ``width`` settled per-second counts (oldest first)."""
        current_sec = int(self.elapsed())
        series: list[int] = []
        start = max(0, current_sec - width)
        for sec in range(start, current_sec):
            series.append(self._rps_buckets.get(sec, 0))
        return series

    def latency_window(self) -> list[float]:
        return list(self._recent_latencies)

    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.success / self.total) * 100.0

    def _percentiles(self, data: list[float]) -> LatencyStats:
        if not data:
            return LatencyStats()
        ordered = sorted(data)

        def pct(p: float) -> float:
            if len(ordered) == 1:
                return ordered[0]
            k = (len(ordered) - 1) * p
            lo = int(k)
            hi = min(lo + 1, len(ordered) - 1)
            frac = k - lo
            return ordered[lo] + (ordered[hi] - ordered[lo]) * frac

        return LatencyStats(
            minimum=self._lat_min or 0.0,
            average=(self._lat_sum / self._seen) if self._seen else 0.0,
            p50=pct(0.50),
            p90=pct(0.90),
            p95=pct(0.95),
            p99=pct(0.99),
            maximum=self._lat_max,
        )

    def live_latency_stats(self) -> LatencyStats:
        """Percentiles over the recent rolling window (cheap, for the dashboard)."""
        return self._percentiles(list(self._recent_latencies))

    def final_latency_stats(self) -> LatencyStats:
        """Percentiles over the whole-test reservoir sample."""
        return self._percentiles(self._reservoir)
