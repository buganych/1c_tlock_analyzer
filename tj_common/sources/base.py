"""Abstract log source."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from tj_common.models import QueryFilters, TjEvent, TransactionBounds


class LogSource(ABC):
    @abstractmethod
    def fetch_victims(self, filters: QueryFilters) -> list[TjEvent]:
        ...

    @abstractmethod
    def find_transaction_bounds(
        self,
        connect_id: str,
        reference_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        neighbor_tx: bool = False,
    ) -> TransactionBounds:
        ...

    def fetch_timeout_wait_tlock(
        self,
        victim: TjEvent,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        timeout_sec: float = 20.0,
        duration_tolerance_sec: float = 2.0,
        ts_window_sec: float = 1.0,
    ) -> TjEvent | None:
        """TLOCK on victim connection with duration close to lock wait timeout."""
        return None

    @abstractmethod
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
        ...

    @abstractmethod
    def fetch_context(
        self,
        connect_id: str,
        before_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
    ) -> str:
        ...

    @abstractmethod
    def fetch_transaction_context(
        self,
        connect_id: str,
        at_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
    ) -> str:
        """Context at SDBL row timestamp (begin/commit), else nearest Context event."""
        ...
