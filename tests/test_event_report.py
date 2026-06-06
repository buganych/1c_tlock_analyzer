"""Structured per-event report with conflict TLOCK."""

from datetime import datetime, timedelta

from tj_common.analysis.pipeline import run_analysis
from tj_common.models import QueryFilters, TjEvent
from tj_common.report.markdown import render_markdown
from tj_common.sources.memory import MemoryLogSource

LOG_ID = "test_log"
REGIONS = "InfoRg17707.DIMS"
LOCKS = (
    "InfoRg17707.DIMS Exclusive "
    "Fld17708=17552:9e5b0050560133fc11f0458ad37f53ef"
)


def _conflict_scenario() -> MemoryLogSource:
    base = datetime(2026, 5, 27, 10, 54, 35)
    events = [
        TjEvent(
            ts=base - timedelta(seconds=30),
            event="SDBL",
            connect_id="500546",
            func="BeginTransaction",
            context="BEGIN",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base - timedelta(seconds=5),
            event="TLOCK",
            connect_id="500546",
            regions=REGIONS,
            locks=LOCKS,
            context="CULPRIT_TLOCK",
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
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base + timedelta(seconds=10),
            event="SDBL",
            connect_id="500546",
            func="CommitTransaction",
            context="END",
            log_id=LOG_ID,
        ),
    ]
    return MemoryLogSource(events)


def test_markdown_shows_intersection_tlocks():
    result = run_analysis(_conflict_scenario(), QueryFilters(log_ids=[LOG_ID]))
    culprit = result.victims[0].culprits[0]
    assert culprit.tx_tlocks_conflict or culprit.full_match
    md = render_markdown(result)
    assert "### Жертва" in md
    assert "518868" in md
    assert "500546" in md
    assert "TLOCK с пересечением" in md
    assert REGIONS in md
    assert "Начало транзакции" in md
    assert "Конец транзакции" in md
    assert "BEGIN" not in md
    assert "END" not in md
    assert "CULPRIT_TLOCK" in md
    assert "**Контекст TLOCK**" in md
