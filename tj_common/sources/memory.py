"""In-memory log source for file-based adapters."""

from __future__ import annotations

from datetime import datetime

from tj_common.models import QueryFilters, TjEvent, TransactionBounds
from tj_common.sources.base import LogSource
from tj_common.utils import (
    host_variants,
    is_begin_transaction,
    is_end_transaction,
    pick_timeout_wait_tlock,
    sql_like_match,
)


class MemoryLogSource(LogSource):
    def __init__(self, events: list[TjEvent], victim_event: str = "TLOCK"):
        self.events = sorted(events, key=lambda e: e.ts)
        self.victim_event = victim_event

    def _host_match(self, event: TjEvent, hosts: list[str] | None) -> bool:
        if not hosts:
            return True
        variants = {h.lower() for h in host_variants(hosts)}
        return event.host.lower() in variants

    def _log_id_match(self, event: TjEvent, log_id: str | None) -> bool:
        if not log_id:
            return True
        return event.log_id == log_id

    def _file_like_match(self, event: TjEvent, pattern: str | None) -> bool:
        if not pattern:
            return True
        file_val = str(event.raw.get("file") or "")
        return sql_like_match(file_val, pattern)

    def fetch_victims(self, filters: QueryFilters) -> list[TjEvent]:
        result = []
        for e in self.events:
            if e.event != self.victim_event:
                continue
            if not e.wait_connections.strip():
                continue
            if not filters.matches_time(e.ts):
                continue
            if e.duration_us < filters.min_duration_us:
                continue
            if not filters.matches_log_id(e.log_id):
                continue
            if not self._host_match(e, filters.hosts):
                continue
            if filters.process_name and e.process_name.lower() != filters.process_name.lower():
                continue
            if not self._file_like_match(e, filters.file_like):
                continue
            result.append(e)
        return result

    def fetch_timeout_wait_tlock(
        self,
        victim: TjEvent,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        timeout_sec: float = 20.0,
        duration_tolerance_sec: float = 2.0,
        ts_window_sec: float = 1.0,
    ) -> TjEvent | None:
        candidates = []
        for e in self.events:
            if e.event != "TLOCK":
                continue
            if not self._host_match(e, hosts):
                continue
            if not self._log_id_match(e, log_id or victim.log_id or None):
                continue
            candidates.append(e)
        return pick_timeout_wait_tlock(
            candidates,
            victim,
            timeout_sec=timeout_sec,
            duration_tolerance_sec=duration_tolerance_sec,
            ts_window_sec=ts_window_sec,
        )

    def find_transaction_bounds(
        self,
        connect_id: str,
        reference_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        neighbor_tx: bool = False,
    ) -> TransactionBounds:
        begins = []
        ends = []
        for e in self.events:
            if e.connect_id != connect_id:
                continue
            if not self._host_match(e, hosts):
                continue
            if not self._log_id_match(e, log_id):
                continue
            if e.event != "SDBL" or not e.func:
                continue
            if is_begin_transaction(e.func) and e.ts < reference_ts:
                begins.append(e.ts)
            elif is_end_transaction(e.func) and e.ts > reference_ts:
                ends.append(e.ts)

        begins.sort(reverse=True)
        ends.sort()
        offset = 1 if neighbor_tx else 0
        if len(begins) <= offset:
            return TransactionBounds(error="Ошибка поиска начала транзакции")
        tx_start = begins[offset]
        tx_end = ends[offset] if len(ends) > offset else datetime.now()
        return TransactionBounds(start=tx_start, end=tx_end)

    def fetch_culprit_tlocks(
        self,
        connect_id: str,
        tx_start: datetime,
        tx_end: datetime,
        region_filter: str,
        victim_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        limit: int = 2001,
    ) -> list[TjEvent]:
        spaces = [s.strip().replace("'", "") for s in region_filter.split(",") if s.strip()]
        result = []
        for e in self.events:
            if e.event != "TLOCK" or e.connect_id != connect_id:
                continue
            if e.ts < tx_start or e.ts > tx_end:
                continue
            if not self._host_match(e, hosts):
                continue
            if not self._log_id_match(e, log_id):
                continue
            if spaces and not any(sp in e.regions for sp in spaces):
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    def fetch_context(
        self,
        connect_id: str,
        before_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
    ) -> str:
        candidates = []
        for e in self.events:
            if e.event == "Context" and e.connect_id == connect_id and e.ts < before_ts:
                if self._host_match(e, hosts):
                    if self._log_id_match(e, log_id):
                        candidates.append(e)
        if not candidates:
            return ""
        candidates.sort(key=lambda x: x.ts)
        return candidates[0].context

    def fetch_transaction_context(
        self,
        connect_id: str,
        at_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
    ) -> str:
        for e in self.events:
            if (
                e.event == "SDBL"
                and e.connect_id == connect_id
                and e.ts == at_ts
                and e.context.strip()
                and self._host_match(e, hosts)
                and self._log_id_match(e, log_id)
            ):
                return e.context
        return self.fetch_context(connect_id, at_ts, log_id=log_id, hosts=hosts)
