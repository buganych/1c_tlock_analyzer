"""HTML report with TOC."""

from datetime import datetime, timedelta

from tj_common.analysis.deadlock_pipeline import run_deadlock_analysis
from tj_common.analysis.pipeline import run_analysis
from tj_common.analysis.unified_pipeline import UnifiedAnalysisResult
from tj_common.models import QueryFilters, TjEvent
from tj_common.models_deadlock import DeadlockQueryFilters, TdeadlockEvent
from tj_common.report.html import render_event_html, render_unified_html
from tj_common.sources.deadlock_memory import DeadlockMemorySource
from tj_common.sources.memory import MemoryLogSource

LOG_ID = "html_test"
REGIONS = "InfoRg17707.DIMS"
LOCKS = "InfoRg17707.DIMS Exclusive Fld1=1"


def _scenario() -> MemoryLogSource:
    base = datetime(2026, 5, 27, 10, 54, 35)
    events = [
        TjEvent(
            ts=base - timedelta(seconds=30),
            event="SDBL",
            connect_id="500546",
            func="BeginTransaction",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base - timedelta(seconds=5),
            event="TLOCK",
            connect_id="500546",
            regions=REGIONS,
            locks=LOCKS,
            context="CULPRIT_CTX",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base,
            event="TLOCK",
            connect_id="518868",
            wait_connections="500546",
            regions=REGIONS,
            locks=LOCKS,
            duration_us=1_000_000,
            context="VICTIM_CTX",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base + timedelta(seconds=10),
            event="SDBL",
            connect_id="500546",
            func="CommitTransaction",
            log_id=LOG_ID,
        ),
    ]
    return MemoryLogSource(events)


def test_html_has_toc_and_anchor_links():
    result = run_analysis(_scenario(), QueryFilters(log_ids=[LOG_ID]))
    page = render_event_html(result, doc_title="Test report")
    assert "<nav class=\"toc\">" in page
    assert "Оглавление" in page
    assert 'href="#' in page
    assert "Событие #1" in page
    assert "CULPRIT_CTX" in page
    assert 'id="' in page
    assert 'class="tlock-table"' in page
    assert "<details>" in page
    assert "<summary>Контекст</summary>" in page
    assert "Контекст TLOCK" not in page


def test_deadlock_timeline_rendered_as_table():
    base = datetime(2026, 5, 27, 10, 54, 35)
    regions = "InfoRg17707.DIMS"
    locks = "InfoRg17707.DIMS Exclusive Fld1=1"
    dci = f"518868 500546 {regions} Exclusive {locks}, 500546 518868 {regions} Exclusive {locks}"
    tdeadlock = TdeadlockEvent(
        ts=base,
        connect_id="518868",
        session_id="100",
        host="vTerm02",
        process_name="UVI_UTD",
        user="Victim User",
        log_id="deadlock_html",
        deadlock_connection_intersections=dci,
    )
    events = [
        TjEvent(
            ts=base - timedelta(seconds=30),
            event="SDBL",
            connect_id="500546",
            func="BeginTransaction",
            log_id="deadlock_html",
        ),
        TjEvent(
            ts=base - timedelta(seconds=25),
            event="TLOCK",
            connect_id="500546",
            regions=regions,
            locks=locks,
            context="P2_LOCK_CTX",
            host="vTerm02",
            log_id="deadlock_html",
        ),
        TjEvent(
            ts=base - timedelta(seconds=20),
            event="SDBL",
            connect_id="518868",
            func="BeginTransaction",
            host="vTerm02",
            log_id="deadlock_html",
        ),
        TjEvent(
            ts=base - timedelta(seconds=15),
            event="TLOCK",
            connect_id="518868",
            regions=regions,
            locks=locks,
            wait_connections="500546",
            context="P1_WAIT_CTX",
            host="vTerm02",
            log_id="deadlock_html",
        ),
        TjEvent(
            ts=base - timedelta(seconds=10),
            event="TLOCK",
            connect_id="500546",
            regions=regions,
            locks=locks,
            wait_connections="518868",
            context="P2_WAIT_CTX",
            host="vTerm02",
            log_id="deadlock_html",
        ),
        TjEvent(
            ts=base + timedelta(seconds=5),
            event="SDBL",
            connect_id="518868",
            func="RollbackTransaction",
            host="vTerm02",
            log_id="deadlock_html",
        ),
        TjEvent(
            ts=base + timedelta(seconds=10),
            event="SDBL",
            connect_id="500546",
            func="CommitTransaction",
            host="vTerm02",
            log_id="deadlock_html",
        ),
    ]
    deadlock = run_deadlock_analysis(
        DeadlockMemorySource([tdeadlock], events),
        DeadlockQueryFilters(log_ids=["deadlock_html"]),
    )
    page = render_unified_html(UnifiedAnalysisResult(tdeadlock=deadlock))
    assert 'class="timeline-table"' in page
    assert "<th>Время</th><th>Участник</th><th>Событие</th>" in page
    assert "Начало транзакции" in page
    assert "Фиксация транзакции" in page
    assert "Пространство:" in page
    assert "Блокировка" in page
    assert "Ожидание" in page
    assert "P1_WAIT_CTX" in page
    assert "<summary>Контекст</summary>" in page
