"""Aggregate multiple NIGHTFALL JSON reports into one combined summary.

This supports *horizontal scale* the legitimate way: you run independent
NIGHTFALL instances on several load generators you own (each with its own real
IP, its own authorization confirmation and the same per-node safety ceiling),
then merge their JSON reports here into a single aggregate view.

It is a pure, offline analysis step — it does not generate traffic, coordinate
nodes, or open any connection. Latency percentiles cannot be reconstructed
exactly from per-node summaries, so pooled percentiles are request-weighted
approximations and are labelled as such.
"""
from __future__ import annotations

import json
from pathlib import Path


def _weighted(values: list[tuple[float, int]]) -> float:
    """Request-count-weighted mean of (value, weight) pairs."""
    total_w = sum(w for _, w in values)
    if total_w <= 0:
        return 0.0
    return sum(v * w for v, w in values) / total_w


def load_reports(paths: list[Path]) -> list[dict]:
    reports: list[dict] = []
    for p in paths:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "total_requests" not in data:
            raise ValueError(f"{p} does not look like a NIGHTFALL JSON report.")
        reports.append(data)
    if not reports:
        raise ValueError("No reports to merge.")
    return reports


def merge_reports(reports: list[dict]) -> dict:
    """Combine per-node reports into one aggregate report dict."""
    n = len(reports)

    def total(key: str) -> int:
        return int(sum(r.get(key, 0) for r in reports))

    total_requests = total("total_requests")
    successful = total("successful_requests")
    failed = total("failed_requests")

    # Status buckets and codes: additive.
    status_buckets: dict[str, int] = {}
    status_codes: dict[str, int] = {}
    errors: dict[str, int] = {}
    for r in reports:
        for k, v in (r.get("status_buckets") or {}).items():
            status_buckets[k] = status_buckets.get(k, 0) + int(v)
        for k, v in (r.get("status_codes") or {}).items():
            status_codes[str(k)] = status_codes.get(str(k), 0) + int(v)
        for k, v in (r.get("errors") or {}).items():
            errors[k] = errors.get(k, 0) + int(v)

    # Latency: min/max exact; averages/percentiles request-weighted approximations.
    def lat_field(field: str, reducer: str) -> float:
        pairs: list[tuple[float, int]] = []
        raw: list[float] = []
        for r in reports:
            lat = r.get("latency") or {}
            if field in lat:
                w = int(r.get("total_requests", 0))
                pairs.append((float(lat[field]), w))
                raw.append(float(lat[field]))
        if not raw:
            return 0.0
        if reducer == "min":
            return min(raw)
        if reducer == "max":
            return max(raw)
        return round(_weighted(pairs), 2)

    latency = {
        "min_ms": lat_field("min_ms", "min"),
        "avg_ms": lat_field("avg_ms", "wavg"),
        "p50_ms": lat_field("p50_ms", "wavg"),
        "p90_ms": lat_field("p90_ms", "wavg"),
        "p95_ms": lat_field("p95_ms", "wavg"),
        "p99_ms": lat_field("p99_ms", "wavg"),
        "max_ms": lat_field("max_ms", "max"),
    }

    targets = sorted({r.get("target", "?") for r in reports})
    aggregate_avg_rps = round(sum(float(r.get("average_rps", 0.0)) for r in reports), 2)
    sum_peak_rps = round(sum(float(r.get("peak_requests_per_second", 0.0)) for r in reports), 2)
    max_duration = max((float(r.get("duration_actual", 0.0)) for r in reports), default=0.0)

    success_rate = round((successful / total_requests * 100.0), 2) if total_requests else 0.0

    observations = [
        f"Aggregated {n} node report(s) covering target(s): {', '.join(targets)}.",
        f"Combined {total_requests:,} requests: {successful:,} succeeded, {failed:,} failed.",
        f"Aggregate average throughput ~{aggregate_avg_rps:.1f} req/sec across all nodes.",
        "Peak req/sec is the SUM of per-node peaks (an upper bound; node peaks "
        "may not have occurred at the same instant).",
        "Pooled latency percentiles are request-weighted approximations of the "
        "per-node percentiles, not exact percentiles over the combined dataset.",
        "Each node ran independently under its own authorization and per-node "
        "safety ceiling; concurrent simulated users and req/sec are not "
        "equivalent to real human visitors.",
    ]

    return {
        "merged": True,
        "node_count": n,
        "targets": targets,
        "duration_actual_max": round(max_duration, 2),
        "configured_users_total": total("configured_users"),
        "peak_active_users_total": total("peak_active_users"),
        "total_requests": total_requests,
        "successful_requests": successful,
        "failed_requests": failed,
        "success_rate": success_rate,
        "aggregate_average_rps": aggregate_avg_rps,
        "peak_requests_per_second_sum": sum_peak_rps,
        "total_bytes": total("total_bytes"),
        "latency": latency,
        "status_buckets": status_buckets,
        "status_codes": dict(sorted(status_codes.items())),
        "errors": errors,
        "per_node": [
            {
                "target": r.get("target"),
                "total_requests": r.get("total_requests"),
                "success_rate": r.get("success_rate"),
                "average_rps": r.get("average_rps"),
                "peak_requests_per_second": r.get("peak_requests_per_second"),
            }
            for r in reports
        ],
        "observations": observations,
    }
