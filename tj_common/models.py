"""Data models for TLOCK analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class QueryFilters:
    """Filters for loading and scoping tech journal events."""

    log_ids: list[str] | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    min_duration_us: int = 0
    hosts: list[str] | None = None
    process_name: str | None = None
    file_like: str | None = None  # ClickHouse: file LIKE pattern, e.g. %tlock_1607235%

    def matches_log_id(self, log_id: str) -> bool:
        if not self.log_ids:
            return True
        return log_id in self.log_ids

    def matches_time(self, ts: datetime) -> bool:
        if self.time_from is not None and ts <= self.time_from:
            return False
        if self.time_to is not None and ts > self.time_to:
            return False
        return True


@dataclass
class TjEvent:
    """Normalized tech journal event."""

    ts: datetime
    event: str
    connect_id: str = ""
    wait_connections: str = ""
    regions: str = ""
    locks: str = ""
    duration_us: int = 0
    host: str = ""
    process_name: str = ""
    user: str = ""
    context: str = ""
    func: str | None = None
    escalating: bool = False
    application_name: str = ""
    trans: int = 0
    log_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        return self.duration_us / 1_000_000


@dataclass
class LockConflictResult:
    has_conflict: bool = False
    conflict_type: str | None = None  # ПолноеСоответствие, Эскалация, РазныйНаборИзмерений


@dataclass
class TransactionBounds:
    start: datetime | None = None
    end: datetime | None = None
    error: str | None = None


@dataclass
class TxBoundary:
    """Transaction begin/end marker with context (when conflict not found)."""

    timestamp: datetime | None = None
    context: str = ""


@dataclass
class CulpritTlockRow:
    """One TLOCK in culprit transaction for report."""

    timestamp: datetime
    duration_sec: float
    regions: str
    locks: str = ""
    context: str = ""
    conflict_type: str = ""


@dataclass
class CulpritAnalysis:
    connect_id: str
    tx_start: datetime | None = None
    tx_end: datetime | None = None
    tx_duration_us: int | None = None
    error: str | None = None
    full_match: list[dict[str, Any]] = field(default_factory=list)
    escalation: list[dict[str, Any]] = field(default_factory=list)
    different_dimensions: list[dict[str, Any]] = field(default_factory=list)
    big_transaction: list[dict[str, Any]] = field(default_factory=list)
    transaction_events: str = ""
    tx_start_boundary: TxBoundary | None = None
    tx_end_boundary: TxBoundary | None = None
    tx_tlocks_conflict: list[CulpritTlockRow] = field(default_factory=list)
    tx_tlocks_all: list[CulpritTlockRow] = field(default_factory=list)


@dataclass
class VictimAnalysis:
    event: TjEvent
    culprits: list[CulpritAnalysis] = field(default_factory=list)
    parse_error: str | None = None


@dataclass
class AnalysisResult:
    victims: list[VictimAnalysis] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
