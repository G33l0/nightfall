"""Result exporters for NIGHTFALL.

All exporters deliberately exclude sensitive request data (Authorization
headers, cookies, request bodies, credentials) from their output — see spec
sections 22 and 14.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from core.engine import TestReport

from .csv_export import export_csv
from .json_export import export_json
from .text_export import export_text

__all__ = ["export_json", "export_csv", "export_text", "export_all", "default_stamp"]


def default_stamp() -> str:
    """A filename stamp that is unique across parallel instances.

    Includes the process id so multiple NIGHTFALL instances (e.g. several
    terminal tabs on one machine) exporting in the same second never overwrite
    each other's reports.
    """
    return f"{datetime.now():%Y-%m-%d_%H%M%S}_pid{os.getpid()}"


def export_all(report: TestReport, results_dir: Path, stamp: str | None = None) -> dict[str, Path]:
    """Write JSON, CSV and TXT reports; return a map of format -> path."""
    if stamp is None:
        stamp = default_stamp()
    results_dir.mkdir(parents=True, exist_ok=True)
    base = results_dir / f"test_{stamp}"
    return {
        "json": export_json(report, base.with_suffix(".json")),
        "csv": export_csv(report, base.with_suffix(".csv")),
        "txt": export_text(report, base.with_suffix(".txt")),
    }
