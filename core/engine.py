"""The load-test engine: orchestrates the worker pool and the test lifecycle.

Responsibilities (spec section 9):
* build a controlled, *bounded* worker pool (never an unlimited task set);
* own the shared aiohttp session, rate limiter and concurrency semaphore;
* schedule ramp-up so users are introduced gradually (spec section 10);
* expose pause / resume / stop control and clean, graceful shutdown;
* produce a final :class:`TestReport` from the collected metrics.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable, Optional

import aiohttp

from .limiter import RateLimiter
from .metrics import LatencyStats, MetricsCollector
from .models import LoadConfig, TargetConfig, TestConfig
from .worker import Control, Worker

log = logging.getLogger("nightfall.engine")


@dataclass(slots=True)
class TestReport:
    """The immutable summary of a completed test."""

    timestamp: str
    target: str
    method: str
    duration_configured: int
    duration_actual: float
    configured_users: int
    peak_active_users: int
    ramp_up: int
    rps_limit: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    success_rate: float
    average_rps: float
    peak_requests_per_second: float
    total_bytes: int
    latency: dict[str, float]
    status_buckets: dict[str, int]
    status_codes: dict[int, int]
    errors: dict[str, int]
    observations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class LoadTestEngine:
    """Runs one load test and yields a :class:`TestReport`."""

    def __init__(self, config: TestConfig) -> None:
        self.config = config
        self.metrics = MetricsCollector(
            method=config.load.method.value, path=config.target.path
        )
        self.control = Control()
        self._workers: list[asyncio.Task] = []
        self._done = False

    @property
    def target(self) -> TargetConfig:
        return self.config.target

    @property
    def load(self) -> LoadConfig:
        return self.config.load

    # -- control passthrough ----------------------------------------------
    def pause(self) -> None:
        self.control.pause()

    def resume(self) -> None:
        self.control.resume()

    def stop(self) -> None:
        self.control.stop()

    @property
    def is_paused(self) -> bool:
        return self.control.paused

    @property
    def finished(self) -> bool:
        return self._done

    # -- main entry point --------------------------------------------------
    async def run(self, on_tick: Optional[Callable[[], Awaitable[None]]] = None) -> TestReport:
        load = self.load
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=load.connect_timeout,
            sock_connect=load.connect_timeout,
            sock_read=load.request_timeout,
        )
        connector = aiohttp.TCPConnector(
            limit=load.users,
            limit_per_host=load.users,
            ttl_dns_cache=300,
        )
        limiter = RateLimiter(load.rps)
        semaphore = asyncio.Semaphore(load.users)

        self.metrics.mark_start()
        started = time.monotonic()
        deadline = started + load.duration

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            skip_auto_headers=["User-Agent"] if "User-Agent" in load.headers else None,
        ) as session:
            # Spawn a *bounded* pool: exactly ``users`` worker tasks.
            for uid in range(1, load.users + 1):
                ramp_delay = self._ramp_delay_for(uid, load)
                worker = Worker(
                    user_id=uid,
                    session=session,
                    target=self.target,
                    load=load,
                    limiter=limiter,
                    semaphore=semaphore,
                    metrics=self.metrics,
                    control=self.control,
                    deadline=deadline,
                    ramp_delay=ramp_delay,
                )
                self._workers.append(asyncio.create_task(worker.run(), name=f"user-{uid}"))

            # Drive the periodic UI tick until the deadline or an early stop.
            await self._supervise(deadline, on_tick)

            # Graceful shutdown of any still-running workers.
            await self._shutdown_workers()

        self.metrics.update_peak_rps()
        self._done = True
        return self._build_report(actual_duration=time.monotonic() - started)

    def _ramp_delay_for(self, uid: int, load: LoadConfig) -> float:
        if load.ramp_up <= 0 or load.users <= 1:
            return 0.0
        # User 1 starts at t=0, user N starts at t=ramp_up.
        return (uid - 1) / (load.users - 1) * load.ramp_up

    async def _supervise(
        self, deadline: float, on_tick: Optional[Callable[[], Awaitable[None]]]
    ) -> None:
        while True:
            if self.control.stopped:
                return
            now = time.monotonic()
            if now >= deadline:
                return
            if all(w.done() for w in self._workers) and self._workers:
                return
            self.metrics.update_peak_rps()
            if on_tick is not None:
                await on_tick()
            await asyncio.sleep(0.15)

    async def _shutdown_workers(self) -> None:
        self.control.stop()
        # Give workers a brief window to notice the stop and exit cleanly.
        pending = [w for w in self._workers if not w.done()]
        if pending:
            done, still = await asyncio.wait(pending, timeout=5.0)
            for task in still:
                task.cancel()
            if still:
                await asyncio.gather(*still, return_exceptions=True)

    # -- reporting ---------------------------------------------------------
    def _build_report(self, actual_duration: float) -> TestReport:
        from datetime import datetime, timezone

        m = self.metrics
        stats = m.final_latency_stats()
        observations = self._observations(stats)

        return TestReport(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            target=self.target.url,
            method=self.load.method.value,
            duration_configured=self.load.duration,
            duration_actual=round(actual_duration, 2),
            configured_users=self.load.users,
            peak_active_users=m.peak_active_users,
            ramp_up=self.load.ramp_up,
            rps_limit=self.load.rps,
            total_requests=m.total,
            successful_requests=m.success,
            failed_requests=m.failed,
            success_rate=round(m.success_rate(), 2),
            average_rps=round(m.average_rps(), 2),
            peak_requests_per_second=round(m.peak_rps, 2),
            total_bytes=m.total_bytes,
            latency=stats.as_dict(),
            status_buckets=dict(m.status_buckets),
            status_codes=dict(sorted(m.status_codes.items())),
            errors=dict(m.errors),
            observations=observations,
        )

    def _observations(self, stats: LatencyStats) -> list[str]:
        """Neutral, factual observations only (spec section 20)."""
        m = self.metrics
        obs: list[str] = []
        obs.append(
            f"The configured test generated a peak of {m.peak_rps:.1f} requests/sec "
            f"and averaged {m.average_rps():.1f} requests/sec."
        )
        obs.append(f"{m.total:,} requests were sent; {m.success:,} succeeded and {m.failed:,} failed.")
        if m.status_buckets["5xx"] == 0:
            obs.append("No HTTP 5xx responses were observed.")
        else:
            obs.append(f"{m.status_buckets['5xx']:,} HTTP 5xx responses were observed.")
        if m.status_buckets["4xx"] > 0:
            obs.append(f"{m.status_buckets['4xx']:,} HTTP 4xx responses were observed.")
        if m.errors:
            top = sorted(m.errors.items(), key=lambda kv: kv[1], reverse=True)[0]
            obs.append(f"The most common connection-level error was '{top[0]}' ({top[1]:,}).")
        obs.append(
            f"Observed latency: P50 {stats.p50:.0f}ms, P95 {stats.p95:.0f}ms, "
            f"P99 {stats.p99:.0f}ms, max {stats.maximum:.0f}ms."
        )
        obs.append(
            "Note: concurrent simulated users and requests/sec are NOT equivalent to "
            "real human visitors. These figures describe how the target responded to "
            "this synthetic HTTP traffic only."
        )
        return obs
