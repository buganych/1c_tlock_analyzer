"""TDEADLOCK analysis (port of АнализВзаимоблокировок1C)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from tj_common.analysis.locks import (
    LockProperties,
    locks_conflict,
    parse_lock_properties,
)
from tj_common.models_deadlock import (
    DeadlockCase,
    LockEdge,
    Participant,
    ParticipantWait,
    TimelineEvent,
    TdeadlockEvent,
)

DCI_PATTERN = re.compile(
    r"(\d+)\s+(\d+)\s+(\w+\.\w+)\s+(\w+)\s+(.+?)(?:,|\'|$)",
    re.IGNORECASE,
)

DEADLOCK_TYPE_ESCALATION = "Повышение уровня блокировки в рамках одной транзакции"
DEADLOCK_TYPE_ORDER = "Разный порядок захвата ресурсов"
MIN_TIMELINE_EVENTS = 8

ROLE_VICTIM = "Участник 1 (Жертва)"
ROLE_P2 = "Участник 2"
ROLE_P3 = "Участник 3"


def parse_deadlock_intersections(
    dci: str, victim_connect_id: str
) -> tuple[list[LockEdge], list[str], Participant, Participant, Participant | None, int]:
    """Port of РазобратьDeadlockConnectionIntersections."""
    edges: list[LockEdge] = []
    tables: list[str] = []
    p1 = Participant(connect_id=victim_connect_id, role=ROLE_VICTIM)
    p2 = Participant(role=ROLE_P2)
    p3 = Participant(role=ROLE_P3)
    seen_other: list[str] = []

    def _assign_other(connect: str, table: str) -> None:
        nonlocal p2, p3
        if connect == victim_connect_id:
            return
        if connect in seen_other:
            return
        seen_other.append(connect)
        if not p2.connect_id:
            p2.connect_id = connect
            p2.table = table
        elif not p3.connect_id:
            p3.connect_id = connect
            p3.table = table

    for m in DCI_PATTERN.finditer(dci.replace("'", "")):
        wait_id, block_id, table, mode, locks = m.groups()
        locks = locks.strip()
        resources = parse_lock_properties(table, f"{table} {mode} {locks}")
        edges.append(edge := LockEdge(
            wait_connect_id=wait_id,
            block_connect_id=block_id,
            table=table,
            mode=mode,
            locks=locks,
            resources=resources,
        ))
        if table not in tables:
            tables.append(table)

        if wait_id == victim_connect_id:
            p1.table = table or p1.table
        else:
            _assign_other(wait_id, table)

        if block_id == victim_connect_id:
            p1.table = table or p1.table
        else:
            _assign_other(block_id, table)

    participant_count = len(edges) if edges else 2
    p3_out = p3 if p3.connect_id else None
    return edges, tables, p1, p2, p3_out, participant_count


def edge_participants(
    case: DeadlockCase, edge: LockEdge
) -> tuple[Participant, Participant]:
    """Port of УчастникиБлокировки."""
    parts = {p.connect_id: p for p in case.participants() if p.connect_id}
    victim = parts.get(edge.wait_connect_id)
    culprit = parts.get(edge.block_connect_id)
    if victim is None:
        victim = case.victim
    if culprit is None:
        culprit = case.participant2
    return victim, culprit


def _wait_matches_dci(wait: ParticipantWait, dci: str) -> bool:
    pattern = (
        rf".*{re.escape(wait.connect_id)}\s+\d+\s+{re.escape(wait.locks)}"
    )
    if re.search(pattern, dci, re.IGNORECASE):
        return True
    if wait.properties and wait.properties[0].mode == "Exclusive":
        if wait.locks and wait.locks in dci:
            return True
    return False


def _conflicts_with_edges(wait: ParticipantWait, edges: list[LockEdge]) -> bool:
    props = wait.properties or parse_lock_properties(wait.regions, wait.locks)
    for edge in edges:
        result = locks_conflict(props, edge.resources)
        if result.has_conflict:
            return True
    return False


def filter_participant_waits(
    waits: list[ParticipantWait],
    edges: list[LockEdge],
    dci: str,
    culprit_connect_id: str,
) -> list[ParticipantWait]:
    """Port of ЗаполнитьОжидания_SQL filtering logic."""
    result: list[ParticipantWait] = []
    seen_locks: list[str] = []
    had_blocking = False
    had_wait = False

    for w in sorted(waits, key=lambda x: x.ts or datetime.min):
        if w.wait_connections:
            ids = [x.strip() for x in w.wait_connections.split(",") if x.strip()]
            if culprit_connect_id not in ids and not w.wait_previous_tx:
                w.wait_connections = ""
        if w.locks in seen_locks:
            continue

        if _wait_matches_dci(w, dci) or (
            w.properties
            and w.properties[0].mode == "Exclusive"
            and w.locks in dci
        ):
            is_deadlock = True
            w.level = w.properties[0].mode if w.properties else ""
        elif not _conflicts_with_edges(w, edges):
            continue
        else:
            is_deadlock = True
            w.level = w.properties[0].mode if w.properties else ""

        is_wait = bool(w.wait_connections.strip())
        if had_blocking and not is_wait:
            continue
        if had_wait and is_wait:
            continue

        seen_locks.append(w.locks)
        w.is_wait = is_wait
        result.append(w)
        if is_wait:
            had_wait = True
        else:
            had_blocking = True

    return result


def match_conflicting_waits(
    case: DeadlockCase,
    victim_waits: list[ParticipantWait],
    culprit_waits: list[ParticipantWait],
    victim_role: str,
    culprit_role: str,
) -> None:
    """Port of КонфликтующиеБлокировки."""
    seen_v: set[str] = set()
    seen_c: set[str] = set()

    for vw in victim_waits:
        if not any(t in vw.regions for t in case.tables):
            continue
        for cw in culprit_waits:
            v_props = vw.properties or parse_lock_properties(vw.regions, vw.locks)
            c_props = cw.properties or parse_lock_properties(cw.regions, cw.locks)
            result = locks_conflict(c_props, v_props)
            if not result.has_conflict:
                continue

            vw.conflicting_resources = c_props if isinstance(c_props, list) else []

            v_key = vw.locks + vw.context
            if v_key not in seen_v:
                seen_v.add(v_key)
                eid = str(uuid.uuid4())
                vw.event_id = eid
                case.timeline.append(
                    TimelineEvent(
                        time=vw.ts_str,
                        role=victim_role,
                        label=vw.locks,
                        is_wait=vw.is_wait,
                        event_id=eid,
                        wait=vw,
                    )
                )

            if cw.regions != vw.regions:
                v_table = case.tables[0] if case.tables else ""
                cw_region = re.search(r"\w+", cw.regions)
                if cw_region and cw_region.group(0) != v_table:
                    if not cw.is_wait:
                        continue

            c_key = cw.locks + cw.context
            if c_key not in seen_c:
                seen_c.add(c_key)
                eid = str(uuid.uuid4())
                cw.event_id = eid
                case.timeline.append(
                    TimelineEvent(
                        time=cw.ts_str,
                        role=culprit_role,
                        label=cw.locks,
                        is_wait=cw.is_wait,
                        event_id=eid,
                        wait=cw,
                    )
                )


def add_tx_events(case: DeadlockCase, participant: Participant, role: str, end_label: str) -> None:
    if participant.tx_start_ts:
        case.timeline.append(
            TimelineEvent(
                time=participant.tx_start_ts,
                role=role,
                label="Начало транзакции",
                is_wait=False,
            )
        )
    if participant.tx_end_ts:
        case.timeline.append(
            TimelineEvent(
                time=participant.tx_end_ts,
                role=role,
                label=end_label,
                is_wait=False,
            )
        )


def _timeline_event_time(ev: TimelineEvent) -> datetime:
    if ev.wait and ev.wait.ts:
        ts = ev.wait.ts
        return ts.replace(tzinfo=None) if ts.tzinfo else ts
    raw = ev.time.strip()
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)


def _timeline_event_order(ev: TimelineEvent) -> int:
    if ev.label in ("Начало транзакции", "BeginTransaction"):
        return 0
    if not ev.is_wait and ev.event_id:
        return 1
    if ev.is_wait:
        return 2
    if ev.label in ("Откат транзакции", "RollbackTransaction"):
        return 3
    if ev.label in ("Фиксация транзакции", "CommitTransaction"):
        return 4
    return 5


def sort_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """Port of УпорядочитьСобытияВзаимоблокировки."""

    def order_key(ev: TimelineEvent) -> tuple[datetime, int]:
        return (_timeline_event_time(ev), _timeline_event_order(ev))

    return sorted(events, key=order_key)


def classify_deadlock_type(victim: Participant) -> str:
    """Port of ТипВзаимоблокировки (simplified header)."""
    had_exclusive = False
    for w in victim.waits:
        if w.level == "Shared" and not had_exclusive:
            return DEADLOCK_TYPE_ESCALATION
        if w.level == "Exclusive":
            had_exclusive = True
    return DEADLOCK_TYPE_ORDER


def _participant_column_title(participant: Participant) -> str:
    return participant.role or f"connect {participant.connect_id}"


def build_cross_matrix(case: DeadlockCase) -> str:
    """ASCII cross matrix V/X for participants."""
    participants = [p for p in case.participants() if p.connect_id]
    if not participants:
        return ""

    def cell(p: Participant, w: ParticipantWait) -> str:
        mark = "X" if w.is_wait else "V"
        region = (w.regions or "").split(",")[0].strip()[:30]
        level = w.level or "?"
        return f"_{mark}_{region} {level}_"

    rows: list[str] = []
    col_widths: list[int] = []

    for p in participants:
        cells = [cell(p, w) for w in p.waits[:5]] or ["_?_"]
        col_widths.append(max(len(c) for c in cells))

    header = (
        "|"
        + "|".join(
            f"{_participant_column_title(p):^{w}}" for p, w in zip(participants, col_widths)
        )
        + "|"
    )
    rows.append(header)
    sep = "|" + "|".join("_" * w for w in col_widths) + "|"

    max_rows = max(len(p.waits) for p in participants) or 1
    for i in range(max_rows):
        line_cells = []
        for p, width in zip(participants, col_widths):
            if i < len(p.waits):
                c = cell(p, p.waits[i])
            else:
                c = "_" * width
            line_cells.append(c.center(width))
        rows.append("|" + "|".join(line_cells) + "|")
        rows.append(sep)

    return "\n".join(rows)


def build_graph_wait_block(case: DeadlockCase) -> dict[str, Any]:
    """Port of СформироватьДанныеДляГрафаJSON."""
    data: dict[str, Any] = {
        "Context_0_block": "",
        "Context_0_wait": "",
        "Context_1_block": "",
        "Context_1_wait": "",
        "Context_2_block": "",
        "Context_2_wait": "",
        "Resource0": "",
        "Resource1": "",
        "Resource2": "",
        "Usr0": case.victim.user,
        "Usr1": case.participant2.user,
        "Usr2": str(case.participant3.user if case.participant3 else ""),
        "Actor_count": case.participant_count,
        "UsrBoxLenght": 30,
        "ContextBoxLenght": 30,
    }
    role_map = {
        ROLE_VICTIM: 0,
        ROLE_P2: 1,
        ROLE_P3: 2,
    }
    for ev in case.timeline:
        if not ev.event_id or not ev.wait:
            continue
        idx = role_map.get(ev.role)
        if idx is None:
            continue
        ctx_lines = (ev.wait.context or "").splitlines()
        last_line = ctx_lines[-1].strip() if ctx_lines else ""
        resource = f"{ev.wait.regions} {ev.wait.level}".strip()
        if ev.is_wait:
            data[f"Context_{idx}_wait"] = last_line
        else:
            data[f"Context_{idx}_block"] = last_line
            data[f"Resource{idx}"] = resource
        if case.participant_count >= 3 and ev.role == ROLE_P3:
            data["Actor_count"] = 3
    return data


def build_graph_locks(case: DeadlockCase) -> dict[str, Any]:
    """Port of НовыйГрафБлокировок / БлокировкиУчастника."""

    def participant_graph(p: Participant) -> dict[str, str]:
        lock_parts: list[str] = []
        wait_parts: list[str] = []
        for w in p.waits:
            for prop in w.properties or []:
                if isinstance(prop, LockProperties):
                    lock_parts.append(f"{prop.space} {prop.mode}")
                    for k, v in prop.fields.items():
                        lock_parts.append(f"ttt{k}: {v}")
            chunk = "nnn".join(lock_parts)
            if w.is_wait:
                wait_parts.append(chunk)
            else:
                lock_parts.append(chunk)
        return {
            "lock": "nnn".join([x for w in p.waits if not w.is_wait for x in [w.locks]]),
            "wait": "nnn".join([x for w in p.waits if w.is_wait for x in [w.locks]]),
        }

    root: dict[str, Any] = {
        "Участник1": participant_graph(case.victim),
        "Участник2": participant_graph(case.participant2),
    }
    if case.participant3 and case.participant3.connect_id:
        root["Участник3"] = participant_graph(case.participant3)
    return root


def build_timeline_text(case: DeadlockCase) -> str:
    lines = [
        f"Тип взаимоблокировки: {case.deadlock_type}",
        "Более подробно: https://its.1c.ru/db/metod8dev/content/4051/hdoc",
        "",
        "Deadlock intersection:",
        case.event.deadlock_connection_intersections.replace("'", ""),
        "",
    ]
    for ev in case.timeline:
        if ev.wait:
            kind = "ОЖИДАНИЕ" if ev.is_wait else "Блокировка"
            lines.append(f"{ev.time}\t{ev.role}\t{kind}")
            lines.append(f"\tПространство: {ev.wait.regions} {ev.wait.level}")
            if ev.wait.context:
                lines.append(f"Контекст:{ev.wait.context[:500]}")
        else:
            lines.append(f"{ev.time}\t{ev.role}\t{ev.label}")
    return "\n".join(lines)


def finalize_case(case: DeadlockCase) -> None:
    case.timeline = sort_timeline(case.timeline)
    case.deadlock_type = classify_deadlock_type(case.victim)
    case.cross_matrix = build_cross_matrix(case)
    case.graph_wait_block = build_graph_wait_block(case)
    case.graph_locks = build_graph_locks(case)
    case.timeline_text = build_timeline_text(case)

    header = [
        f"Тип взаимоблокировки: {case.deadlock_type}",
        "",
        "Deadlock intersection:",
        case.event.deadlock_connection_intersections.replace("'", ""),
    ]
    case.text_graph = "\n".join(header)

    tx_events = sum(
        1 for e in case.timeline if e.label in ("Начало транзакции", "Откат транзакции", "Фиксация транзакции")
    )
    lock_events = sum(1 for e in case.timeline if e.event_id)

    if len(case.timeline) < MIN_TIMELINE_EVENTS:
        case.status = "too_few_events"
        case.status_detail = f"Событий {len(case.timeline)}, нужно >= {MIN_TIMELINE_EVENTS}"
    else:
        case.status = "ok"
        case.status_detail = ""

    p2_ids = case.participant2.connect_id
    if case.participant3 and case.participant3.connect_id:
        case.culprit_connect_ids = f"{p2_ids}/{case.participant3.connect_id}"
    else:
        case.culprit_connect_ids = p2_ids
