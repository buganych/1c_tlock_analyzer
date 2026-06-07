"""Tests for interactive CALL HTML report."""

from datetime import datetime

from tj_common.analysis.call_aggregate import buckets_to_result, aggregate_call_events
from tj_common.models_call import CallEvent
from tj_common.report.call_html import render_call_html


def test_render_call_html_has_filter_sort_and_total():
    events = [
        CallEvent(
            ts=datetime(2026, 6, 4),
            module="Alpha",
            method="Run",
            duration_us=2_000_000,
            cpu_time_us=1_000_000,
            memory_peak=2 * 1024 * 1024,
            in_bytes=1024,
            out_bytes=512,
        ),
        CallEvent(
            ts=datetime(2026, 6, 4),
            module="Beta",
            method="Go",
            duration_us=4_000_000,
            cpu_time_us=3_000_000,
            memory_peak=4 * 1024 * 1024,
            in_bytes=2048,
            out_bytes=1024,
        ),
    ]
    result = buckets_to_result(
        aggregate_call_events(events),
        filters_summary={"source": "test"},
        visible_rows=1,
    )
    html = render_call_html(result)
    assert 'id="ctx-filter"' in html
    assert "window.CALL_REPORT=" in html
    assert '"total":' in html
    assert "sortable" in html
    assert "Всего (" in html
    assert "Фильтр" in html
