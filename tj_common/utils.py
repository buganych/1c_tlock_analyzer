"""Shared utilities."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser

from tj_common.models import TjEvent

MCP_CLICKHOUSE_SERVER = "mcp-clickhouse"


def parse_datetime(value: str) -> datetime:
    return date_parser.parse(value)


def host_variants(hosts: list[str] | None) -> list[str]:
    """1C uses lower/upper host names in queries."""
    if not hosts:
        return []
    result: list[str] = []
    for h in hosts:
        result.append(h)
        result.append(h.lower())
        result.append(h.upper())
    return list(dict.fromkeys(result))


def sql_like_match(value: str, pattern: str) -> bool:
    """Match string against SQL LIKE pattern (% and _ wildcards)."""
    import re

    parts: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "%":
            parts.append(".*")
            i += 1
        elif ch == "_":
            parts.append(".")
            i += 1
        else:
            j = i
            while j < len(pattern) and pattern[j] not in "%_":
                j += 1
            parts.append(re.escape(pattern[i:j]))
            i = j
    regex = "^" + "".join(parts) + "$"
    return bool(re.match(regex, value))


DEFAULT_LOCK_WAIT_TIMEOUT_SEC = 20.0
TIMEOUT_TLOCK_DURATION_TOLERANCE_SEC = 2.0
TIMEOUT_TLOCK_TS_WINDOW_SEC = 1.0


def normalize_wait_connections(value: str) -> frozenset[str]:
    return frozenset(
        part.strip().replace("'", "")
        for part in value.split(",")
        if part.strip()
    )


def wait_connections_equal(left: str, right: str) -> bool:
    return normalize_wait_connections(left) == normalize_wait_connections(right)


def pick_timeout_wait_tlock(
    candidates: list[TjEvent],
    victim: TjEvent,
    *,
    timeout_sec: float = DEFAULT_LOCK_WAIT_TIMEOUT_SEC,
    duration_tolerance_sec: float = TIMEOUT_TLOCK_DURATION_TOLERANCE_SEC,
    ts_window_sec: float = TIMEOUT_TLOCK_TS_WINDOW_SEC,
) -> TjEvent | None:
    """Pick victim's TLOCK wait that ended in timeout (~20s duration)."""
    best: tuple[float, float, TjEvent] | None = None
    for event in candidates:
        if event.event != "TLOCK" or not event.wait_connections.strip():
            continue
        if event.connect_id != victim.connect_id:
            continue
        if not wait_connections_equal(event.wait_connections, victim.wait_connections):
            continue
        ts_delta = abs((event.ts - victim.ts).total_seconds())
        if ts_delta > ts_window_sec:
            continue
        if event.duration_us <= 0:
            continue
        duration_delta = abs(event.duration_sec - timeout_sec)
        if duration_delta > duration_tolerance_sec:
            continue
        score = (duration_delta, ts_delta)
        if best is None or score < (best[0], best[1]):
            best = (duration_delta, ts_delta, event)
    return best[2] if best else None


def wait_start_ts(victim_ts: datetime, duration_us: int) -> datetime:
    """Moment when wait began: victim_ts - duration (BSL logic)."""
    total_us = int(victim_ts.timestamp() * 1_000_000) - duration_us
    if total_us < 0:
        return victim_ts - timedelta(seconds=duration_us / 1_000_000)
    sec, us = divmod(total_us, 1_000_000)
    return datetime.fromtimestamp(sec).replace(microsecond=us)


def format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def is_begin_transaction(func: str | None) -> bool:
    return (func or "").strip() == "BeginTransaction"


def is_end_transaction(func: str | None) -> bool:
    f = (func or "").strip()
    if f in ("CommitTransaction", "RollbackTransaction"):
        return True
    return "CommitTransaction" in f or "RollbackTransaction" in f


def event_to_dict(event: Any) -> dict[str, Any]:

    if not isinstance(event, TjEvent):
        return dict(event)
    return {
        "Timestamp": format_ts(event.ts),
        "log_id": event.log_id,
        "Event": event.event,
        "ConnectID": event.connect_id,
        "WaitConnections": event.wait_connections,
        "Regions": event.regions,
        "Locks": event.locks,
        "Duration": event.duration_us,
        "Host": event.host,
        "ProcessName": event.process_name,
        "Usr": event.user,
        "Context": event.context,
        "Func": event.func or "",
        "Escalating": "true" if event.escalating else "false",
        "ApplicationName": event.application_name,
    }


def find_mcp_json_path() -> Path | None:
    """Locate .cursor/mcp.json from cwd upward, then package root."""
    for base in [Path.cwd(), *Path.cwd().parents]:
        path = base / ".cursor" / "mcp.json"
        if path.is_file():
            return path
    pkg_path = Path(__file__).resolve().parents[1] / ".cursor" / "mcp.json"
    if pkg_path.is_file():
        return pkg_path
    return None


def load_mcp_clickhouse_env() -> dict[str, str]:
    """Read mcp-clickhouse env block from .cursor/mcp.json (gitignored)."""
    path = find_mcp_json_path()
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers") or {}
    block = servers.get(MCP_CLICKHOUSE_SERVER) or {}
    env = block.get("env") or {}
    return {str(k): str(v) for k, v in env.items()}


def apply_mcp_clickhouse_env() -> None:
    """Set os.environ from mcp.json where not already defined (for CLI/scripts)."""
    for key, value in load_mcp_clickhouse_env().items():
        os.environ.setdefault(key, value)


def _clickhouse_setting(name: str, mcp: dict[str, str], default: str = "") -> str:
    return os.environ.get(name) or mcp.get(name) or default


def clickhouse_config_from_env() -> dict[str, Any]:
    """
    ClickHouse client config: env vars override .cursor/mcp.json (mcp-clickhouse).

    Tables tj_* live in database onec_logs; if MCP has CLICKHOUSE_DATABASE=default,
    use CLICKHOUSE_LOG_DATABASE from mcp/env or fallback onec_logs.
    """
    mcp = load_mcp_clickhouse_env()
    database = _clickhouse_setting("CLICKHOUSE_DATABASE", mcp, "onec_logs")
    if database == "default":
        database = _clickhouse_setting("CLICKHOUSE_LOG_DATABASE", mcp, "onec_logs")

    secure_raw = _clickhouse_setting("CLICKHOUSE_SECURE", mcp, "false")
    return {
        "host": _clickhouse_setting("CLICKHOUSE_HOST", mcp, "localhost"),
        "port": int(_clickhouse_setting("CLICKHOUSE_PORT", mcp, "8123")),
        "username": _clickhouse_setting("CLICKHOUSE_USER", mcp, "default"),
        "password": _clickhouse_setting("CLICKHOUSE_PASSWORD", mcp, ""),
        "database": database,
        "secure": secure_raw.lower() in ("1", "true", "yes"),
    }
