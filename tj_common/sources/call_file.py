"""Plain / JSON CALL event loader with chunked iteration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from tj_common.models_call import CallEvent, CallQueryFilters
from tj_common.sources.plain import (
    EVENT_LINE_RE,
    _normalize_prop_key,
    _parse_kv_props,
    _parse_time_part,
)

CALL_PLAIN_KEYS = {
    "Module",
    "Method",
    "Func",
    "MName",
    "IName",
    "CPUTime",
    "MemoryPeak",
    "InBytes",
    "OutBytes",
    "Context",
}


def _int_field(props: dict[str, str], *keys: str) -> int:
    for key in keys:
        raw = props.get(key)
        if raw is None or raw == "":
            continue
        try:
            return int(float(raw))
        except ValueError:
            continue
    return 0


def _map_call_props(props: dict[str, str], ts: datetime, duration_us: int) -> CallEvent:
    return CallEvent(
        ts=ts,
        context_raw=props.get("Context") or props.get("context") or "",
        module=props.get("Module") or props.get("module") or "",
        method=props.get("Method") or props.get("method") or "",
        func=props.get("Func") or props.get("func") or "",
        mname=props.get("MName") or props.get("mname") or "",
        iname=props.get("IName") or props.get("iname") or "",
        duration_us=duration_us,
        cpu_time_us=_int_field(props, "CPUTime", "cpu_time"),
        memory_peak=_int_field(props, "MemoryPeak", "memory_peak"),
        in_bytes=_int_field(props, "InBytes", "in_bytes"),
        out_bytes=_int_field(props, "OutBytes", "out_bytes"),
        log_id=str(props.get("log_id") or props.get("LogId") or ""),
        process_name=props.get("pprocessName")
        or props.get("ProcessName")
        or props.get("process_name")
        or "",
        host=props.get("tcomputerName")
        or props.get("Host")
        or props.get("computer_name")
        or "",
        raw=props,
    )


def _event_matches_filters(event: CallEvent, filters: CallQueryFilters) -> bool:
    if event.duration_us < filters.min_duration_us:
        return False
    if not filters.matches_log_id(event.log_id):
        return False
    if not filters.matches_time(event.ts):
        return False
    if not filters.matches_host(event.host):
        return False
    if not filters.matches_process(event.process_name):
        return False
    return True


def parse_plain_call_content(
    content: str,
    *,
    base_date: datetime | None = None,
    filters: CallQueryFilters | None = None,
) -> list[CallEvent]:
    if base_date is None:
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    events: list[CallEvent] = []
    i = 0
    while i < len(lines):
        m = EVENT_LINE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        time_part, duration_str, event_name, _level, tail = m.groups()
        if event_name != "CALL":
            i += 1
            continue

        ts = _parse_time_part(time_part, base_date)
        duration_us = int(duration_str)
        props: dict[str, str] = {"Duration": duration_str}
        for part in tail.split(","):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                props[_normalize_prop_key(k.strip())] = v.strip()
        extra_props, next_i = _parse_kv_props(lines, i + 1)
        props.update(extra_props)
        event = _map_call_props(props, ts, duration_us)
        if filters is None or _event_matches_filters(event, filters):
            events.append(event)
        i = next_i
    return events


def _get_json_field(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        source = row.get("_source")
        if isinstance(source, dict) and key in source:
            return source[key]
    return default


def _normalize_json_call(row: dict[str, Any]) -> CallEvent | None:
    event = str(_get_json_field(row, "Event", "event", "name", default=""))
    if event != "CALL":
        return None
    ts_val = _get_json_field(row, "ts", "Timestamp", "@timestamp", "timestamp")
    if isinstance(ts_val, datetime):
        ts = ts_val.replace(tzinfo=None) if ts_val.tzinfo else ts_val
    else:
        ts = datetime.fromisoformat(str(ts_val).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    duration = int(_get_json_field(row, "Duration", "duration", default=0) or 0)
    return CallEvent(
        ts=ts,
        context_raw=str(_get_json_field(row, "context", "Context", default="")),
        module=str(_get_json_field(row, "module", "Module", default="")),
        method=str(_get_json_field(row, "method", "Method", default="")),
        func=str(_get_json_field(row, "func", "Func", default="")),
        mname=str(_get_json_field(row, "mname", "MName", default="")),
        iname=str(_get_json_field(row, "iname", "IName", default="")),
        duration_us=duration,
        cpu_time_us=int(_get_json_field(row, "cpu_time", "CPUTime", default=0) or 0),
        memory_peak=int(_get_json_field(row, "memory_peak", "MemoryPeak", default=0) or 0),
        in_bytes=int(_get_json_field(row, "in_bytes", "InBytes", default=0) or 0),
        out_bytes=int(_get_json_field(row, "out_bytes", "OutBytes", default=0) or 0),
        log_id=str(_get_json_field(row, "log_id", "LogId", default="")),
        process_name=str(
            _get_json_field(row, "process_name", "ProcessName", "pprocessName", default="")
        ),
        host=str(_get_json_field(row, "computer_name", "Host", "tcomputerName", default="")),
        raw=row,
    )


def parse_json_call_content(
    content: str,
    *,
    filters: CallQueryFilters | None = None,
) -> list[CallEvent]:
    content = content.strip()
    if not content:
        return []
    events: list[CallEvent] = []
    try:
        data = json.loads(content)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("events") or data.get("records") or [data]
        else:
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = _normalize_json_call(row)
            if event and (filters is None or _event_matches_filters(event, filters)):
                events.append(event)
        return events
    except json.JSONDecodeError:
        pass

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        event = _normalize_json_call(row)
        if event and (filters is None or _event_matches_filters(event, filters)):
            events.append(event)
    return events


def iter_plain_call_chunks(
    path: str | Path,
    *,
    base_date: datetime | None,
    filters: CallQueryFilters,
    chunk_size: int,
) -> Iterator[list[CallEvent]]:
    """Yield CALL events from plain file in bounded batches."""
    if base_date is None:
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.lstrip("\ufeff").splitlines()
    batch: list[CallEvent] = []
    i = 0
    while i < len(lines):
        m = EVENT_LINE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        time_part, duration_str, event_name, _level, tail = m.groups()
        if event_name != "CALL":
            i += 1
            continue
        ts = _parse_time_part(time_part, base_date)
        duration_us = int(duration_str)
        props: dict[str, str] = {"Duration": duration_str}
        for part in tail.split(","):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                props[_normalize_prop_key(k.strip())] = v.strip()
        extra_props, next_i = _parse_kv_props(lines, i + 1)
        props.update(extra_props)
        event = _map_call_props(props, ts, duration_us)
        if _event_matches_filters(event, filters):
            batch.append(event)
            if len(batch) >= chunk_size:
                yield batch
                batch = []
        i = next_i
    if batch:
        yield batch


def iter_json_call_chunks(
    path: str | Path,
    *,
    filters: CallQueryFilters,
    chunk_size: int,
) -> Iterator[list[CallEvent]]:
    """Yield CALL events from JSON/NDJSON file in bounded batches."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace").strip()
    batch: list[CallEvent] = []

    def flush() -> Iterator[list[CallEvent]]:
        nonlocal batch
        if batch:
            out = batch
            batch = []
            return iter([out])
        return iter([])

    try:
        data = json.loads(text)
        rows: list[dict[str, Any]]
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            raw = data.get("events") or data.get("records") or [data]
            rows = [r for r in raw if isinstance(r, dict)]
        else:
            rows = []
        for row in rows:
            event = _normalize_json_call(row)
            if event and _event_matches_filters(event, filters):
                batch.append(event)
                if len(batch) >= chunk_size:
                    yield batch
                    batch = []
        yield from flush()
        return
    except json.JSONDecodeError:
        pass

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        event = _normalize_json_call(row)
        if event and _event_matches_filters(event, filters):
            batch.append(event)
            if len(batch) >= chunk_size:
                yield batch
                batch = []
    yield from flush()
