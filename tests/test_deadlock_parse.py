"""Unit tests for TDEADLOCK parsing and classification."""

from datetime import datetime

from tj_common.analysis.deadlock import (
    DEADLOCK_TYPE_ESCALATION,
    DEADLOCK_TYPE_ORDER,
    build_cross_matrix,
    classify_deadlock_type,
    parse_deadlock_intersections,
    sort_timeline,
)
from tj_common.models_deadlock import (
    DeadlockCase,
    Participant,
    ParticipantWait,
    TimelineEvent,
    TdeadlockEvent,
)


DCI_TWO = (
    "518868 500546 InfoRg17707.DIMS Exclusive "
    "InfoRg17707.DIMS Exclusive Fld17708=1, "
    "500546 518868 InfoRg17707.DIMS Exclusive "
    "InfoRg17707.DIMS Exclusive Fld17709=2"
)


def test_parse_dci_two_participants():
    edges, tables, p1, p2, p3, count = parse_deadlock_intersections(DCI_TWO, "518868")
    assert len(edges) == 2
    assert "InfoRg17707.DIMS" in tables
    assert p1.connect_id == "518868"
    assert p2.connect_id in ("500546", "518868")
    assert p3 is None
    assert count == 2


def test_classify_escalation():
    victim = Participant(
        waits=[
            ParticipantWait(
                ts_str="",
                ts=datetime.now(),
                connect_id="1",
                level="Shared",
                is_wait=True,
                properties=[],
            )
        ]
    )
    assert classify_deadlock_type(victim) == DEADLOCK_TYPE_ESCALATION


def test_classify_order():
    victim = Participant(
        waits=[
            ParticipantWait(
                ts_str="",
                ts=datetime.now(),
                connect_id="1",
                level="Exclusive",
                is_wait=False,
                properties=[],
            )
        ]
    )
    assert classify_deadlock_type(victim) == DEADLOCK_TYPE_ORDER


def test_sort_timeline_mixed_time_formats():
    """Lock events from memory used isoformat (T), tx events use strftime (space)."""
    events = [
        TimelineEvent(time="2026-06-05 11:13:49.273001", role="Участник 2", label="Фиксация транзакции"),
        TimelineEvent(
            time="2026-06-05T11:13:49.260017",
            role="Участник 2",
            label="locks",
            is_wait=True,
            event_id="w2",
            wait=ParticipantWait(
                ts_str="2026-06-05T11:13:49.260017",
                ts=datetime(2026, 6, 5, 11, 13, 49, 260017),
                is_wait=True,
            ),
        ),
        TimelineEvent(time="2026-06-05 11:13:30.048002", role="Участник 1 (Жертва)", label="Начало транзакции"),
        TimelineEvent(
            time="2026-06-05T11:13:30.049010",
            role="Участник 1 (Жертва)",
            label="locks",
            is_wait=False,
            event_id="l1",
            wait=ParticipantWait(
                ts_str="2026-06-05T11:13:30.049010",
                ts=datetime(2026, 6, 5, 11, 13, 30, 49010),
                is_wait=False,
            ),
        ),
        TimelineEvent(time="2026-06-05 11:13:39.006002", role="Участник 2", label="Начало транзакции"),
        TimelineEvent(time="2026-06-05 11:13:49.259009", role="Участник 1 (Жертва)", label="Откат транзакции"),
    ]
    ordered = sort_timeline(events)
    labels = [e.label for e in ordered]
    assert labels[0] == "Начало транзакции"
    assert ordered[0].role == "Участник 1 (Жертва)"
    assert labels[1] == "locks"
    assert labels[2] == "Начало транзакции"
    assert ordered[2].role == "Участник 2"
    assert labels[-1] == "Фиксация транзакции"
    times = [_timeline_ts(e) for e in ordered]
    assert times == sorted(times)


def _timeline_ts(ev: TimelineEvent) -> datetime:
    if ev.wait and ev.wait.ts:
        return ev.wait.ts
    return datetime.fromisoformat(ev.time.replace("T", " "))


def test_cross_matrix_nonempty():
    case = DeadlockCase(
        event=TdeadlockEvent(ts=datetime.now(), connect_id="1"),
        victim=Participant(
            connect_id="1",
            role="Участник 1 (Жертва)",
            waits=[
                ParticipantWait(
                    ts_str="t",
                    ts=datetime.now(),
                    connect_id="1",
                    regions="T.DIMS",
                    level="Exclusive",
                    is_wait=False,
                )
            ],
        ),
        participant2=Participant(
            connect_id="2",
            role="Участник 2",
            waits=[
                ParticipantWait(
                    ts_str="t",
                    ts=datetime.now(),
                    connect_id="2",
                    regions="T.DIMS",
                    level="Shared",
                    is_wait=True,
                )
            ],
        ),
    )
    matrix = build_cross_matrix(case)
    assert "Участник 1 (Жертва)" in matrix
    assert "Участник 2" in matrix
    assert "_Участник 1 (_" not in matrix
