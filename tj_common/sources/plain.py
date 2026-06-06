"""Plain text 1C tech journal parser."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from tj_common.models import TjEvent
from tj_common.sources.memory import MemoryLogSource

# 28:34.123012-1234567,TLOCK,2,...  (MM:SS.micro within hour from log file name)
# 10:54:35.123456-...               (HH:MM:SS.micro, full clock time)
EVENT_LINE_RE = re.compile(
    r"^(\d{2}:\d{2}(?::\d{2})?\.\d+)-(\d+),(\w+),(\d+),(.*)$"
)
KV_RE = re.compile(r"^(\w+)=([\s\S]*)$")

RELEVANT_EVENTS = {"TLOCK", "TTIMEOUT", "TDEADLOCK", "SDBL", "Context"}


def _normalize_prop_key(key: str) -> str:
    """Map TJ plain keys like t:connectID -> tconnectID."""
    if key.startswith("t:"):
        return "t" + key[2:]
    if key.startswith("p:"):
        return "p" + key[2:]
    return key


def _parse_time_part(time_part: str, base_date: datetime) -> datetime:
    parts = time_part.split(":")
    sec, _, micro = parts[-1].partition(".")
    micro_val = int(micro.ljust(6, "0")[:6])
    if len(parts) == 3:
        hour, minute = int(parts[0]), int(parts[1])
    else:
        hour = base_date.hour
        minute = int(parts[0])
    return base_date.replace(
        hour=hour,
        minute=minute,
        second=int(sec),
        microsecond=micro_val,
    )


def _parse_kv_props(lines: list[str], start_idx: int) -> tuple[dict[str, str], int]:
    props: dict[str, str] = {}
    i = start_idx
    while i < len(lines):
        line = lines[i].rstrip("\n\r")
        if EVENT_LINE_RE.match(line):
            break
        m = KV_RE.match(line.strip())
        if m:
            key, val = m.group(1), m.group(2).strip()
            props[key] = val
        elif line.strip() and props:
            last_key = list(props.keys())[-1]
            props[last_key] += "\n" + line.strip()
        i += 1
    return props, i


def _map_props(props: dict[str, str], event_name: str) -> TjEvent:
    ts_raw = props.get("@timestamp") or props.get("DateTime") or ""
    if ts_raw:
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", ""))
        except ValueError:
            ts = datetime.now()
    else:
        ts = datetime.now()

    connect = (
        props.get("tconnectID")
        or props.get("ConnectID")
        or props.get("connect_id")
        or ""
    )
    duration = int(
        props.get("duration")
        or props.get("Duration")
        or props.get("durationInSecond", 0)
        or 0
    )
    if "durationInSecond" in props:
        try:
            duration = int(float(props["durationInSecond"]) * 1_000_000)
        except ValueError:
            duration = 0

    escalating = str(props.get("Escalating", "")).lower() == "true"
    func = props.get("Func") or props.get("func")

    return TjEvent(
        ts=ts,
        event=event_name,
        log_id=str(props.get("log_id") or props.get("LogId") or ""),
        connect_id=str(connect).replace("'", ""),
        wait_connections=str(
            props.get("WaitConnections") or props.get("wait_connections") or ""
        ).replace("'", ""),
        regions=str(props.get("Regions") or props.get("regions") or "").replace("'", ""),
        locks=str(props.get("Locks") or props.get("locks") or "").replace("'", ""),
        duration_us=duration,
        host=props.get("agent.hostname")
        or props.get("tcomputerName")
        or props.get("Host")
        or props.get("computer_name")
        or "",
        process_name=props.get("pprocessName")
        or props.get("ProcessName")
        or props.get("process_name")
        or "",
        user=props.get("Usr") or props.get("usr") or "",
        context=props.get("Context") or props.get("context") or "",
        func=func,
        escalating=escalating,
        application_name=props.get("tapplicationName")
        or props.get("ApplicationName")
        or "",
        raw=props,
    )


def parse_plain_content(
    content: str,
    base_date: datetime | None = None,
) -> list[TjEvent]:
    """Parse flat TJ file content."""
    if base_date is None:
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    events: list[TjEvent] = []
    i = 0
    while i < len(lines):
        m = EVENT_LINE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        time_part, duration_str, event_name, _level, tail = m.groups()
        if event_name not in RELEVANT_EVENTS:
            i += 1
            continue

        ts = _parse_time_part(time_part, base_date)

        props: dict[str, str] = {"Duration": duration_str}
        for part in tail.split(","):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                props[_normalize_prop_key(k.strip())] = v.strip()

        extra_props, next_i = _parse_kv_props(lines, i + 1)
        props.update(extra_props)
        props["@timestamp"] = ts.isoformat()

        ev = _map_props(props, event_name)
        ev.ts = ts
        ev.duration_us = int(duration_str)
        events.append(ev)
        i = next_i

    return events


def load_plain_file(
    path: str | Path,
    base_date: datetime | None = None,
    victim_event: str = "TLOCK",
) -> MemoryLogSource:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return MemoryLogSource(
        parse_plain_content(text, base_date), victim_event=victim_event
    )
