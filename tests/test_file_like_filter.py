"""Tests for optional file LIKE filter on victims."""

from datetime import datetime, timedelta

from tj_common.analysis.pipeline import run_analysis
from tj_common.models import QueryFilters, TjEvent
from tj_common.sources.memory import MemoryLogSource
from tj_common.utils import sql_like_match

REGIONS = "T.Table"
LOCKS = "T.Table Exclusive Fld1=1"
LOG_ID = "test_log"


def test_sql_like_match():
    assert sql_like_match("path/tlock_1607235.log", "%tlock_1607235%")
    assert not sql_like_match("path/other.log", "%tlock_1607235%")


def test_fetch_victims_file_like():
    base = datetime(2026, 6, 4, 10, 0, 0)
    events = [
        TjEvent(
            ts=base,
            event="TLOCK",
            connect_id="1",
            wait_connections="2",
            regions=REGIONS,
            locks=LOCKS,
            duration_us=1_000_000,
            log_id=LOG_ID,
            raw={"file": "slice/tlock_1607235_01.log"},
        ),
        TjEvent(
            ts=base + timedelta(seconds=1),
            event="TLOCK",
            connect_id="3",
            wait_connections="4",
            regions=REGIONS,
            locks=LOCKS,
            duration_us=1_000_000,
            log_id=LOG_ID,
            raw={"file": "slice/other.log"},
        ),
    ]
    source = MemoryLogSource(events)
    all_victims = run_analysis(source, QueryFilters(log_ids=[LOG_ID])).victims
    assert len(all_victims) == 2

    sliced = run_analysis(
        source,
        QueryFilters(log_ids=[LOG_ID], file_like="%tlock_1607235%"),
    ).victims
    assert len(sliced) == 1
    assert sliced[0].event.connect_id == "1"
