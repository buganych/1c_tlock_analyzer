"""End-to-end TTIMEOUT pipeline tests with in-memory events."""

from datetime import datetime, timedelta

import pytest

from tj_common.models import QueryFilters, TjEvent
from tj_common.sources.memory import MemoryLogSource
from ttimeout_analyzer.pipeline import run_analysis

REGIONS = "InfoRg17707.DIMS"
LOCKS = (
    "InfoRg17707.DIMS Exclusive "
    "Fld17708=17552:9e5b0050560133fc11f0458ad37f53ef "
    "Fld17709=80:9e5b0050560133fc11f0468638b41009 "
    "Fld17710=393:c62745a3cb8472d9dca8babafb232a78"
)
LOG_ID = "test_log"


def _build_scenario() -> MemoryLogSource:
    base = datetime(2026, 5, 27, 10, 54, 35)
    events = [
        TjEvent(
            ts=base - timedelta(seconds=30),
            event="SDBL",
            connect_id="500546",
            func="BeginTransaction",
            host="vTerm02",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base - timedelta(seconds=5),
            event="TLOCK",
            connect_id="500546",
            regions=REGIONS,
            locks=LOCKS,
            host="vTerm02",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base,
            event="TTIMEOUT",
            connect_id="518868",
            wait_connections="500546",
            regions=REGIONS,
            locks=LOCKS,
            duration_us=10_000_000,
            host="vTerm02",
            process_name="UVI_UTD",
            user="Test User",
            log_id=LOG_ID,
        ),
        TjEvent(
            ts=base + timedelta(seconds=10),
            event="SDBL",
            connect_id="500546",
            func="CommitTransaction",
            host="vTerm02",
            log_id=LOG_ID,
        ),
    ]
    return MemoryLogSource(events, victim_event="TTIMEOUT")


def _build_timeout_pair_scenario() -> MemoryLogSource:
    """TTIMEOUT without regions/locks; paired ~20s TLOCK on victim connection."""
    base = datetime(2026, 6, 5, 11, 18, 58, 762000)
    regions = "InfoRg40.DIMS"
    locks = 'InfoRg40.DIMS Shared Fld41="А" Fld42="Б"'
    culprit_locks = 'InfoRg40.DIMS Exclusive Fld41="А" Fld42="Б"'
    events = [
        TjEvent(
            ts=base - timedelta(seconds=36),
            event="SDBL",
            connect_id="7",
            func="BeginTransaction",
            host="app1c04",
            process_name="ex_burm_lock",
        ),
        TjEvent(
            ts=base - timedelta(seconds=36) + timedelta(microseconds=8),
            event="TLOCK",
            connect_id="7",
            regions=regions,
            locks=culprit_locks,
            host="app1c04",
            process_name="ex_burm_lock",
        ),
        TjEvent(
            ts=base,
            event="TTIMEOUT",
            connect_id="8",
            wait_connections="7",
            host="app1c04",
            process_name="ex_burm_lock",
        ),
        TjEvent(
            ts=base + timedelta(microseconds=2),
            event="TLOCK",
            connect_id="8",
            wait_connections="7",
            regions=regions,
            locks=locks,
            duration_us=20_000_002,
            host="app1c04",
            process_name="ex_burm_lock",
        ),
        TjEvent(
            ts=base + timedelta(seconds=10),
            event="SDBL",
            connect_id="7",
            func="CommitTransaction",
            host="app1c04",
            process_name="ex_burm_lock",
        ),
    ]
    return MemoryLogSource(events, victim_event="TTIMEOUT")


def test_ttimeout_resolves_paired_tlock_near_20_seconds():
    source = _build_timeout_pair_scenario()
    result = run_analysis(source, QueryFilters(process_name="ex_burm_lock"))
    assert len(result.victims) == 1
    victim = result.victims[0]
    assert victim.event.event == "TTIMEOUT"
    assert victim.event.regions == "InfoRg40.DIMS"
    assert "Shared" in victim.event.locks
    assert victim.event.duration_sec == pytest.approx(20.0, abs=0.01)
    assert len(victim.culprits) == 1
    culprit = victim.culprits[0]
    assert culprit.connect_id == "7"
    assert culprit.full_match or culprit.tx_tlocks_conflict


def test_ttimeout_pipeline_finds_full_match_by_log_id():
    source = _build_scenario()
    filters = QueryFilters(log_ids=[LOG_ID])
    result = run_analysis(source, filters)
    assert len(result.victims) == 1
    victim = result.victims[0]
    assert victim.event.event == "TTIMEOUT"
    assert victim.event.connect_id == "518868"
    assert len(victim.culprits) == 1
    culprit = victim.culprits[0]
    assert culprit.connect_id == "500546"
    assert culprit.tx_start is not None
    assert len(culprit.full_match) >= 1 or len(culprit.different_dimensions) >= 1
