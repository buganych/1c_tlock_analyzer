"""JSON report serialization."""

from __future__ import annotations

import json
from typing import Any

from tj_common.models import AnalysisResult
from tj_common.report.labels import ReportLabels, TLOCK_LABELS
from tj_common.utils import format_ts


def _tlock_row_dict(row) -> dict[str, Any]:
    return {
        "time": format_ts(row.timestamp),
        "duration_sec": row.duration_sec,
        "regions": row.regions,
        "locks": row.locks,
        "context": row.context,
        "conflict_type": row.conflict_type or None,
    }


def _culprit_report_detail(c) -> dict[str, Any] | None:
    if not (c.tx_start_boundary or c.tx_end_boundary):
        return None
    detail: dict[str, Any] = {}
    if c.tx_start_boundary:
        detail["tx_start"] = {
            "time": format_ts(c.tx_start_boundary.timestamp)
            if c.tx_start_boundary.timestamp
            else None,
            "context": c.tx_start_boundary.context,
        }
    if c.tx_end_boundary:
        detail["tx_end"] = {
            "time": format_ts(c.tx_end_boundary.timestamp)
            if c.tx_end_boundary.timestamp
            else None,
            "tx_duration_sec": (c.tx_duration_us / 1_000_000)
            if c.tx_duration_us
            else None,
            "context": c.tx_end_boundary.context,
        }
    if c.tx_tlocks_conflict:
        detail["tlocks_intersection"] = [_tlock_row_dict(r) for r in c.tx_tlocks_conflict]
    elif c.tx_tlocks_all:
        detail["tlocks_all_in_tx"] = [_tlock_row_dict(r) for r in c.tx_tlocks_all]
    return detail


def _culprit_to_dict(c) -> dict[str, Any]:
    return {
        "connect_id": c.connect_id,
        "tx_start": format_ts(c.tx_start) if c.tx_start else None,
        "tx_end": format_ts(c.tx_end) if c.tx_end else None,
        "tx_duration_sec": (c.tx_duration_us / 1_000_000) if c.tx_duration_us else None,
        "error": c.error,
        "conflicts": {
            "full_match": c.full_match,
            "escalation": c.escalation,
            "different_dimensions": c.different_dimensions,
            "big_transaction": c.big_transaction,
        },
        "report_detail": _culprit_report_detail(c),
    }


def analysis_to_dict(
    result: AnalysisResult, labels: ReportLabels = TLOCK_LABELS
) -> dict[str, Any]:
    victims = []
    for v in result.victims:
        ev = v.event
        victims.append(
            {
                "event_type": labels.json_event_type,
                "timestamp": format_ts(ev.ts),
                "log_id": ev.log_id,
                "connect_id": ev.connect_id,
                "wait_connections": _parse_wait_list(ev.wait_connections),
                "regions": ev.regions,
                "locks": ev.locks,
                "duration_sec": ev.duration_sec,
                "host": ev.host,
                "process_name": ev.process_name,
                "user": ev.user,
                "context": ev.context,
                "parse_error": v.parse_error,
                "culprits": [_culprit_to_dict(c) for c in v.culprits],
            }
        )
    return {
        "analyzer": labels.json_event_type,
        "victims": victims,
        "errors": result.errors,
    }


def _parse_wait_list(wait_connections: str) -> list[str]:
    return [
        x.strip().replace("'", "")
        for x in wait_connections.split(",")
        if x.strip()
    ]


def render_json(
    result: AnalysisResult,
    indent: int = 2,
    labels: ReportLabels = TLOCK_LABELS,
) -> str:
    return json.dumps(
        analysis_to_dict(result, labels=labels),
        ensure_ascii=False,
        indent=indent,
    )
