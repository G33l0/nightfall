"""CSV exporter (flat key/value summary)."""
from __future__ import annotations

import csv
from pathlib import Path

from core.engine import TestReport


def export_csv(report: TestReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    d = report.as_dict()
    rows: list[tuple[str, str]] = []

    for key, value in d.items():
        if isinstance(value, dict):
            for sub, sub_val in value.items():
                rows.append((f"{key}.{sub}", str(sub_val)))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                rows.append((f"{key}[{i}]", str(item)))
        else:
            rows.append((key, str(value)))

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)
    return path
