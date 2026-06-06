"""In-memory TDEADLOCK source for tests."""

from __future__ import annotations

from datetime import datetime

from tj_common.analysis.locks import parse_lock_properties
from tj_common.models import TjEvent, TransactionBounds
from tj_common.models_deadlock import (
    DeadlockQueryFilters,
    ParticipantWait,
    TdeadlockEvent,
)
from tj_common.sources.deadlock_base import DeadlockDataSource


class DeadlockMemorySource(DeadlockDataSource):
    def __init__(
        self,
        tdeadlocks: list[TdeadlockEvent],
        events: list[TjEvent],
    ):
        self.tdeadlocks = sorted(tdeadlocks, key=lambda e: e.ts)
        self.events = sorted(events, key=lambda e: e.ts)

    def fetch_tdeadlocks(self, filters: DeadlockQueryFilters) -> list[TdeadlockEvent]:
        result = []
        for e in self.tdeadlocks:
            if not filters.matches_log_id(e.log_id):
                continue
            if not filters.matches_time(e.ts):
                continue
            if filters.process_name and e.process_name.lower() != filters.process_name.lower():
                continue
            if filters.connect_id and e.connect_id != filters.connect_id:
                continue
            if filters.session_id and e.session_id != filters.session_id:
                continue
            if filters.single_at and e.ts != filters.single_at:
                continue
            result.append(e)
        return result

    def _host_ok(self, event_host: str, host: str | None) -> bool:
        if not host:
            return True
        return event_host.lower() == host.lower()

    def transaction_bounds_at(
        self,
        connect_id: str,
        reference_ts: datetime,
        log_id: str | None,
        host: str | None,
        process_name: str | None,
    ) -> TransactionBounds:
        begins, ends = [], []
        for e in self.events:
            if e.connect_id != connect_id:
                continue
            if log_id and e.log_id != log_id:
                continue
            if not self._host_ok(e.host, host):
                continue
            if e.event != "SDBL" or not e.func:
                continue
            if e.func == "BeginTransaction" and e.ts <= reference_ts:
                begins.append(e.ts)
            elif e.func in ("CommitTransaction", "RollbackTransaction") and e.ts >= reference_ts:
                ends.append(e.ts)
        begins.sort(reverse=True)
        ends.sort()
        if not begins:
            return TransactionBounds(error="Ошибка поиска начала транзакции")
        return TransactionBounds(start=begins[0], end=ends[0] if ends else datetime.now())

    def fetch_participant_tlocks(
        self,
        connect_id: str,
        tx_start: datetime,
        tx_end: datetime,
        tables: list[str],
        host: str | None,
        log_id: str | None,
        process_name: str | None,
        culprit_tx_start: datetime | None,
        culprit_connect_id: str,
    ) -> list[ParticipantWait]:
        waits: list[ParticipantWait] = []
        guilty = culprit_tx_start or tx_start
        for e in self.events:
            if e.event != "TLOCK" or e.connect_id != connect_id:
                continue
            if e.ts < tx_start or e.ts > tx_end:
                continue
            if log_id and e.log_id != log_id:
                continue
            if not self._host_ok(e.host, host):
                continue
            if tables and not any(t in e.regions for t in tables):
                continue
            wc = e.wait_connections
            if wc:
                ids = [x.strip().replace("'", "") for x in wc.split(",")]
                if culprit_connect_id not in ids and e.ts >= guilty:
                    wc = ""
            waits.append(
                ParticipantWait(
                    ts=e.ts,
                    ts_str=e.ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    connect_id=e.connect_id,
                    context=e.context,
                    locks=e.locks,
                    regions=e.regions,
                    wait_connections=wc,
                    wait_previous_tx=e.ts < guilty,
                    properties=parse_lock_properties(e.regions, e.locks),
                )
            )
        return waits

    def fetch_context(
        self,
        connect_id: str,
        at_ts: datetime,
        host: str | None,
        log_id: str | None,
        process_name: str | None,
    ) -> str:
        candidates = [
            e
            for e in self.events
            if e.event == "Context"
            and e.connect_id == connect_id
            and e.ts <= at_ts
            and self._host_ok(e.host, host)
            and (not log_id or e.log_id == log_id)
        ]
        if not candidates:
            return ""
        candidates.sort(key=lambda x: x.ts)
        return candidates[0].context
