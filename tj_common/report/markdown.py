"""Markdown report export."""

from __future__ import annotations

from tj_common.models import AnalysisResult
from tj_common.report.event_report import render_event_markdown
from tj_common.report.labels import ReportLabels, TLOCK_LABELS


def render_markdown(
    result: AnalysisResult, labels: ReportLabels = TLOCK_LABELS
) -> str:
    return render_event_markdown(result, labels)
