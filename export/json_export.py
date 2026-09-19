"""JSON exporter."""
from __future__ import annotations

import json
from pathlib import Path

from core.engine import TestReport


def export_json(report: TestReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.as_dict()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path
