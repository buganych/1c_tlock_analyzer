"""Build all analyzer sources from one TJ file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tj_common.models import TjEvent
from tj_common.sources.deadlock_memory import DeadlockMemorySource
from tj_common.sources.deadlock_plain import events_to_deadlock_source
from tj_common.sources.json_file import parse_json_content
from tj_common.sources.memory import MemoryLogSource
from tj_common.sources.plain import parse_plain_content


def load_unified_plain_file(
    path: str | Path, base_date: datetime | None = None
) -> tuple[MemoryLogSource, MemoryLogSource, DeadlockMemorySource]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    events = parse_plain_content(text, base_date)
    return _sources_from_events(events)


def load_unified_json_file(
    path: str | Path,
) -> tuple[MemoryLogSource, MemoryLogSource, DeadlockMemorySource]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    events = parse_json_content(text)
    return _sources_from_events(events)


def _sources_from_events(
    events: list[TjEvent],
) -> tuple[MemoryLogSource, MemoryLogSource, DeadlockMemorySource]:
    tlock = MemoryLogSource(events, victim_event="TLOCK")
    ttimeout = MemoryLogSource(events, victim_event="TTIMEOUT")
    tdeadlock = events_to_deadlock_source(events)
    return tlock, ttimeout, tdeadlock
