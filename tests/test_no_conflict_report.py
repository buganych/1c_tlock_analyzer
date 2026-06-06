"""Report when culprit transaction has no classified lock conflict."""

from datetime import datetime, timedelta

from tj_common.analysis.pipeline import run_analysis
from tj_common.models import QueryFilters, TjEvent
from tj_common.report.markdown import render_markdown
from tj_common.report.text import render_text
from tj_common.sources.memory import MemoryLogSource

LOG_ID = "test_log"
VICTIM_REGION = "AccumRg10993.DIMS"
OTHER_REGION = "AccumRg10479.RECORDER"


def _no_match_scenario() -> MemoryLogSource:
    base = datetime(2026, 6, 4, 11, 21, 3, 990072)
    tx_start = base - timedelta(seconds=43)
    tx_end = base - timedelta(milliseconds=240)
    events = [
        TjEvent(
            ts=tx_start,
            event="SDBL",
            connect_id="674241",
            func="BeginTransaction",
            context="BEGIN_CTX",
            host="vUTD01",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base - timedelta(seconds=10),
            event="TLOCK",
            connect_id="674241",
            regions=OTHER_REGION,
            locks=f"{OTHER_REGION} Exclusive",
            duration_us=100_000,
            context="TLOCK_CTX",
            host="vUTD01",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base,
            event="TLOCK",
            connect_id="675289",
            wait_connections="674241",
            regions=VICTIM_REGION,
            locks=f"{VICTIM_REGION} Exclusive",
            duration_us=656_841,
            host="vUTD01",
            process_name="UVI_UTD",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=tx_end,
            event="SDBL",
            connect_id="674241",
            func='["Transaction","CommitTransaction"]',
            context="END_CTX",
            host="vUTD01",
            log_id=LOG_ID,
        ),
    ]
    return MemoryLogSource(events)


def test_no_conflict_shows_transaction_and_all_tlocks():
    result = run_analysis(_no_match_scenario(), QueryFilters(log_ids=[LOG_ID]))
    assert len(result.victims) == 1
    culprit = result.victims[0].culprits[0]
    assert not culprit.full_match
    assert len(culprit.tx_tlocks_all) == 1
    assert culprit.tx_start_boundary
    assert culprit.tx_start_boundary.context == "BEGIN_CTX"
    assert culprit.tx_end_boundary
    assert culprit.tx_end_boundary.context == "END_CTX"

    text = render_text(result)
    md = render_markdown(result)
    assert "Начало транзакции" in text
    assert "Все TLOCK" in text
    assert OTHER_REGION in text
    assert "Конец транзакции" in text
    assert "END_CTX" not in text
    assert "### Жертва" in md
    assert "BEGIN_CTX" not in md
    assert "TLOCK с пересечением" in md
    assert "Все TLOCK в транзакции" in md
    assert OTHER_REGION in md
    assert culprit.tx_duration_us is not None
