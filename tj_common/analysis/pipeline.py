"""Main TLOCK analysis pipeline."""

from __future__ import annotations

from dataclasses import replace

from tj_common.analysis.locks import (
    DIFFERENT_DIMENSIONS,
    ESCALATION,
    FULL_MATCH,
    check_full_match_strings,
    locks_conflict,
    parse_lock_properties,
)
from tj_common.models import (
    AnalysisResult,
    CulpritAnalysis,
    CulpritTlockRow,
    QueryFilters,
    TjEvent,
    TxBoundary,
    VictimAnalysis,
)
from tj_common.sources.base import LogSource
from tj_common.utils import event_to_dict, wait_start_ts

BIG_TX_LIMIT = 2001


def _has_classified_conflict(analysis: CulpritAnalysis) -> bool:
    return bool(
        analysis.full_match
        or analysis.escalation
        or analysis.different_dimensions
    )


def _event_to_tlock_row(ev: TjEvent, conflict_type: str = "") -> CulpritTlockRow:
    return CulpritTlockRow(
        timestamp=ev.ts,
        duration_sec=ev.duration_sec,
        regions=ev.regions,
        locks=ev.locks,
        context=ev.context,
        conflict_type=conflict_type,
    )


def _conflict_rows_from_analysis(culprit: CulpritAnalysis) -> list[CulpritTlockRow]:
    rows: list[CulpritTlockRow] = []
    mapping = (
        (FULL_MATCH, culprit.full_match),
        (ESCALATION, culprit.escalation),
        (DIFFERENT_DIMENSIONS, culprit.different_dimensions),
    )
    for label, items in mapping:
        for d in items:
            rows.append(
                CulpritTlockRow(
                    timestamp=_parse_conflict_ts(d.get("Timestamp")),
                    duration_sec=float(d.get("Duration", 0) or 0) / 1_000_000,
                    regions=str(d.get("Regions", "")),
                    locks=str(d.get("Locks", "")),
                    context=str(d.get("Context", "")),
                    conflict_type=label,
                )
            )
    return rows


def _parse_conflict_ts(value: object):
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return datetime.now()


def _fill_culprit_report_detail(
    source: LogSource,
    culprit: CulpritAnalysis,
    victim: TjEvent,
    log_id: str | None,
    hosts: list[str] | None,
) -> None:
    if culprit.error or not culprit.tx_start or not culprit.tx_end:
        return

    culprit.tx_start_boundary = TxBoundary(
        timestamp=culprit.tx_start,
        context=source.fetch_transaction_context(
            culprit.connect_id, culprit.tx_start, log_id=log_id, hosts=hosts
        ),
    )
    culprit.tx_end_boundary = TxBoundary(
        timestamp=culprit.tx_end,
        context=source.fetch_transaction_context(
            culprit.connect_id, culprit.tx_end, log_id=log_id, hosts=hosts
        ),
    )
    if culprit.tx_duration_us is None:
        culprit.tx_duration_us = int(
            (culprit.tx_end - culprit.tx_start).total_seconds() * 1_000_000
        )

    if _has_classified_conflict(culprit):
        culprit.tx_tlocks_conflict = _conflict_rows_from_analysis(culprit)
        return

    if culprit.big_transaction:
        return

    all_tlocks = source.fetch_culprit_tlocks(
        culprit.connect_id,
        culprit.tx_start,
        culprit.tx_end,
        "",
        victim.ts,
        log_id=log_id,
        hosts=hosts,
    )
    rows: list[CulpritTlockRow] = []
    for ev in all_tlocks:
        _ensure_context(source, ev, hosts)
        rows.append(_event_to_tlock_row(ev))
    culprit.tx_tlocks_all = rows


def _resolve_victim_for_analysis(
    source: LogSource,
    victim: TjEvent,
    hosts: list[str] | None,
) -> TjEvent:
    """For TTIMEOUT without locks, use paired ~20s TLOCK on victim connection."""
    if victim.event != "TTIMEOUT":
        return victim
    if victim.regions.strip() and victim.locks.strip():
        return victim

    pair = source.fetch_timeout_wait_tlock(
        victim,
        log_id=victim.log_id or None,
        hosts=hosts,
    )
    if pair is None:
        return victim

    return replace(
        victim,
        regions=pair.regions,
        locks=pair.locks,
        duration_us=pair.duration_us,
        escalating=pair.escalating,
        context=pair.context or victim.context,
    )


def _parse_culprit_ids(wait_connections: str) -> list[str]:
    return [
        c.strip().replace("'", "")
        for c in wait_connections.split(",")
        if c.strip()
    ]


def _ensure_context(
    source: LogSource,
    event: TjEvent,
    hosts: list[str] | None,
) -> None:
    if not event.context.strip():
        event.context = source.fetch_context(
            event.connect_id, event.ts, log_id=event.log_id or None, hosts=hosts
        )


def _analyze_culprit_tlocks(
    victim: TjEvent,
    culprit_id: str,
    tlocks: list[TjEvent],
    source: LogSource,
    hosts: list[str] | None,
) -> CulpritAnalysis:
    analysis = CulpritAnalysis(connect_id=culprit_id)
    victim_props = parse_lock_properties(victim.regions, victim.locks)

    if len(tlocks) >= BIG_TX_LIMIT:
        seen_contexts: set[str] = set()
        for ev in tlocks:
            if ev.context in seen_contexts:
                continue
            seen_contexts.add(ev.context)
            analysis.big_transaction.append(event_to_dict(ev))
        return analysis

    for ev in tlocks:
        _ensure_context(source, ev, hosts)

        if check_full_match_strings(victim.locks, ev.locks):
            conflict_type = FULL_MATCH
            has_conflict = True
        else:
            culprit_props = parse_lock_properties(ev.regions, ev.locks)
            result = locks_conflict(
                victim_props, culprit_props, culprit_escalating=ev.escalating
            )
            has_conflict = result.has_conflict
            conflict_type = result.conflict_type

        if not has_conflict or not conflict_type:
            continue

        data = event_to_dict(ev)
        if conflict_type == FULL_MATCH:
            analysis.full_match.append(data)
        elif conflict_type == ESCALATION:
            analysis.escalation.append(data)
        elif conflict_type == DIFFERENT_DIMENSIONS:
            analysis.different_dimensions.append(data)

    return analysis


def analyze_victim(
    source: LogSource,
    victim: TjEvent,
    hosts: list[str] | None = None,
) -> VictimAnalysis:
    analysis_victim = _resolve_victim_for_analysis(source, victim, hosts)
    result = VictimAnalysis(event=analysis_victim)
    _ensure_context(source, analysis_victim, hosts)

    ref_ts = wait_start_ts(analysis_victim.ts, analysis_victim.duration_us)
    culprit_ids = _parse_culprit_ids(analysis_victim.wait_connections)
    if not culprit_ids:
        result.parse_error = "Empty WaitConnections"
        return result

    log_id = analysis_victim.log_id or None

    for culprit_id in culprit_ids:
        bounds = source.find_transaction_bounds(
            culprit_id, ref_ts, log_id=log_id, hosts=hosts, neighbor_tx=False
        )
        if bounds.error:
            bounds = source.find_transaction_bounds(
                culprit_id, ref_ts, log_id=log_id, hosts=hosts, neighbor_tx=True
            )

        culprit = CulpritAnalysis(connect_id=culprit_id)
        if bounds.error:
            culprit.error = bounds.error
            result.culprits.append(culprit)
            continue

        culprit.tx_start = bounds.start
        culprit.tx_end = bounds.end
        if bounds.start and bounds.end:
            culprit.tx_duration_us = int(
                (bounds.end - bounds.start).total_seconds() * 1_000_000
            )

        tlocks = source.fetch_culprit_tlocks(
            culprit_id,
            bounds.start,
            bounds.end,
            analysis_victim.regions,
            analysis_victim.ts,
            log_id=log_id,
            hosts=hosts,
        )
        analyzed = _analyze_culprit_tlocks(
            analysis_victim, culprit_id, tlocks, source, hosts
        )
        analyzed.tx_start = bounds.start
        analyzed.tx_end = bounds.end
        analyzed.tx_duration_us = culprit.tx_duration_us
        _fill_culprit_report_detail(source, analyzed, analysis_victim, log_id, hosts)
        result.culprits.append(analyzed)

    return result


def run_analysis(source: LogSource, filters: QueryFilters) -> AnalysisResult:
    victims = source.fetch_victims(filters)
    result = AnalysisResult()
    for victim in victims:
        try:
            result.victims.append(
                analyze_victim(source, victim, filters.hosts)
            )
        except Exception as exc:
            result.errors.append(
                f"{victim.ts} connect={victim.connect_id} log_id={victim.log_id}: {exc}"
            )
    return result
