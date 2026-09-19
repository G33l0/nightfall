"""Plain-text (human readable) exporter."""
from __future__ import annotations

from pathlib import Path

from core.engine import TestReport


def _fmt_ms(ms: float) -> str:
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.0f} ms"


def export_text(report: TestReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    d = report
    lat = d.latency
    lines: list[str] = []
    add = lines.append

    add("=" * 60)
    add("NIGHTFALL // LOAD TESTER  —  TEST REPORT")
    add("=" * 60)
    add(f"Timestamp (UTC):      {d.timestamp}")
    add(f"Target:               {d.target}")
    add(f"Method:               {d.method}")
    add(f"Configured duration:  {d.duration_configured} s")
    add(f"Actual duration:      {d.duration_actual} s")
    add(f"Configured users:     {d.configured_users}")
    add(f"Peak active users:    {d.peak_active_users}")
    add(f"Ramp-up:              {d.ramp_up} s")
    add(f"RPS limit:            {d.rps_limit or 'unlimited'}")
    add("")
    add("-" * 60)
    add("TRAFFIC")
    add("-" * 60)
    add(f"Total requests:       {d.total_requests:,}")
    add(f"Successful:           {d.successful_requests:,}")
    add(f"Failed:               {d.failed_requests:,}")
    add(f"Success rate:         {d.success_rate:.2f}%")
    add(f"Average RPS:          {d.average_rps:.2f}")
    add(f"Peak RPS:             {d.peak_requests_per_second:.2f}")
    add(f"Bytes received:       {d.total_bytes:,}")
    add("")
    add("-" * 60)
    add("LATENCY")
    add("-" * 60)
    add(f"Min:                  {_fmt_ms(lat['min_ms'])}")
    add(f"Average:              {_fmt_ms(lat['avg_ms'])}")
    add(f"P50 (median):         {_fmt_ms(lat['p50_ms'])}")
    add(f"P90:                  {_fmt_ms(lat['p90_ms'])}")
    add(f"P95:                  {_fmt_ms(lat['p95_ms'])}")
    add(f"P99:                  {_fmt_ms(lat['p99_ms'])}")
    add(f"Max:                  {_fmt_ms(lat['max_ms'])}")
    add("")
    add("-" * 60)
    add("HTTP STATUS BUCKETS")
    add("-" * 60)
    for bucket, count in d.status_buckets.items():
        add(f"{bucket:<8}{count:,}")
    if d.status_codes:
        add("")
        add("STATUS CODES")
        for code, count in d.status_codes.items():
            add(f"  {code}: {count:,}")
    add("")
    add("-" * 60)
    add("ERRORS")
    add("-" * 60)
    if d.errors:
        for name, count in sorted(d.errors.items(), key=lambda kv: kv[1], reverse=True):
            add(f"{name:<28}{count:,}")
    else:
        add("None recorded.")
    add("")
    add("-" * 60)
    add("OBSERVATIONS")
    add("-" * 60)
    for obs in d.observations:
        add(f"- {obs}")
    add("")
    add("=" * 60)
    add("Note: This report describes synthetic HTTP traffic only. Concurrent")
    add("simulated users and requests/sec are NOT equivalent to real human")
    add("visitors. Only test systems you own or are authorized to test.")
    add("=" * 60)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
