"""Data models for CALL event analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

VISIBLE_ROWS_DEFAULT = 20


@dataclass
class CallQueryFilters:
    """Filters for loading CALL events."""

    log_ids: list[str] | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    min_duration_us: int = 0
    hosts: list[str] | None = None
    process_name: str | None = None
    file_like: str | None = None

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

    def matches_host(self, host: str) -> bool:
        if not self.hosts:
            return True
        return host in self.hosts

    def matches_process(self, process_name: str) -> bool:
        if not self.process_name:
            return True
        return process_name.lower() == self.process_name.lower()


@dataclass
class CallEvent:
    ts: datetime
    context_raw: str = ""
    module: str = ""
    method: str = ""
    func: str = ""
    mname: str = ""
    iname: str = ""
    duration_us: int = 0
    cpu_time_us: int = 0
    memory_peak: int = 0
    in_bytes: int = 0
    out_bytes: int = 0
    log_id: str = ""
    process_name: str = ""
    host: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallTopRow:
    context: str
    count: int
    avg: int
    max: int
    min: int
    total: int


@dataclass
class CallAnalysisResult:
    duration_rows: list[CallTopRow]
    cpu_rows: list[CallTopRow]
    memory_rows: list[CallTopRow]
    disk_total_rows: list[CallTopRow]
    disk_in_rows: list[CallTopRow]
    disk_out_rows: list[CallTopRow]
    total_events: int
    filters_summary: dict[str, Any]
    visible_rows: int = VISIBLE_ROWS_DEFAULT
