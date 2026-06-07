"""JSON report for CALL analysis."""

from __future__ import annotations

import json
from dataclasses import asdict

from tj_common.models_call import CallAnalysisResult


def render_call_json(result: CallAnalysisResult) -> str:
    payload = {
        "analyzer": "call_analyzer",
        "total_events": result.total_events,
        "visible_rows": result.visible_rows,
        "filters": result.filters_summary,
        "duration_rows": [asdict(r) for r in result.duration_rows],
        "cpu_rows": [asdict(r) for r in result.cpu_rows],
        "memory_rows": [asdict(r) for r in result.memory_rows],
        "disk_total_rows": [asdict(r) for r in result.disk_total_rows],
        "disk_in_rows": [asdict(r) for r in result.disk_in_rows],
        "disk_out_rows": [asdict(r) for r in result.disk_out_rows],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
