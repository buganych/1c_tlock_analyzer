"""Shared CLI helpers for tlock-, ttimeout-, and tdeadlock-analyzer."""

from __future__ import annotations

from enum import Enum
from typing import Optional

import typer

from tj_common.models import QueryFilters
from tj_common.models_deadlock import DeadlockQueryFilters
from tj_common.sources.base import LogSource
from tj_common.sources.clickhouse import ClickHouseSource
from tj_common.sources.deadlock_clickhouse import DeadlockClickHouseSource
from tj_common.sources.json_file import load_json_file
from tj_common.sources.plain import load_plain_file
from tj_common.utils import clickhouse_config_from_env, parse_datetime


class SourceType(str, Enum):
    click = "click"
    plain = "plain"
    json = "json"


class OutputType(str, Enum):
    text = "text"
    json = "json"
    markdown = "markdown"
    both = "both"


def parse_csv(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    items = [x.strip() for x in value.split(",") if x.strip()]
    return items or None


def build_filters(
    log_id: Optional[str],
    time_from: Optional[str],
    time_to: Optional[str],
    min_duration: float,
    hosts: Optional[str],
    database: Optional[str],
    source: SourceType,
    file_like: Optional[str] = None,
) -> QueryFilters:
    log_ids = parse_csv(log_id)
    if source == SourceType.click and not log_ids:
        raise typer.BadParameter(
            "For --source click specify --log-id (comma-separated). "
            "Dates --from/--to are optional."
        )

    t_from = parse_datetime(time_from) if time_from else None
    t_to = parse_datetime(time_to) if time_to else None
    if t_from and t_to and t_from >= t_to:
        raise typer.BadParameter("--from must be earlier than --to")

    pattern = (file_like or "").strip() or None
    if pattern and source != SourceType.click:
        raise typer.BadParameter(
            "--file-like applies only to --source click (ClickHouse file column)"
        )

    return QueryFilters(
        log_ids=log_ids,
        time_from=t_from,
        time_to=t_to,
        min_duration_us=int(min_duration * 1_000_000),
        hosts=parse_csv(hosts),
        process_name=database,
        file_like=pattern,
    )


def build_deadlock_filters(
    log_id: Optional[str],
    time_from: Optional[str],
    time_to: Optional[str],
    hosts: Optional[str],
    database: Optional[str],
    source: SourceType,
    at: Optional[str] = None,
    connect_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> DeadlockQueryFilters:
    log_ids = parse_csv(log_id)
    if source == SourceType.click and not log_ids:
        raise typer.BadParameter(
            "For --source click specify --log-id (comma-separated)."
        )

    t_from = parse_datetime(time_from) if time_from else None
    t_to = parse_datetime(time_to) if time_to else None
    if t_from and t_to and t_from >= t_to:
        raise typer.BadParameter("--from must be earlier than --to")

    single_at = parse_datetime(at) if at else None
    if single_at and source == SourceType.click:
        if not connect_id:
            raise typer.BadParameter("--connect-id required with --at for single case")

    return DeadlockQueryFilters(
        log_ids=log_ids,
        time_from=t_from,
        time_to=t_to,
        hosts=parse_csv(hosts),
        process_name=database,
        connect_id=connect_id,
        session_id=session_id,
        single_at=single_at,
    )


def build_clickhouse_source(
    ch_host: Optional[str],
    ch_port: Optional[int],
    ch_user: Optional[str],
    ch_password: Optional[str],
    ch_database: Optional[str],
    *,
    victim_table: str,
    victim_event: str,
) -> ClickHouseSource:
    cfg = clickhouse_config_from_env()
    return ClickHouseSource(
        host=ch_host or cfg["host"],
        port=ch_port or cfg["port"],
        username=ch_user or cfg["username"],
        password=ch_password if ch_password is not None else cfg["password"],
        database=ch_database or cfg["database"],
        secure=cfg["secure"],
        victim_table=victim_table,
        victim_event=victim_event,
    )


def build_deadlock_clickhouse_source(
    ch_host: Optional[str],
    ch_port: Optional[int],
    ch_user: Optional[str],
    ch_password: Optional[str],
    ch_database: Optional[str],
) -> DeadlockClickHouseSource:
    cfg = clickhouse_config_from_env()
    return DeadlockClickHouseSource(
        host=ch_host or cfg["host"],
        port=ch_port or cfg["port"],
        username=ch_user or cfg["username"],
        password=ch_password if ch_password is not None else cfg["password"],
        database=ch_database or cfg["database"],
        secure=cfg["secure"],
    )


def build_file_source(
    source: SourceType,
    file: Optional[str],
    base_date: Optional[str],
    victim_event: str,
) -> LogSource:
    if not file:
        raise typer.BadParameter("--file is required for plain/json sources")
    bd = parse_datetime(base_date) if base_date else None
    if source == SourceType.plain:
        return load_plain_file(file, base_date=bd, victim_event=victim_event)
    return load_json_file(file, victim_event=victim_event)


def print_victim_analysis_output(
    console,
    result,
    output: OutputType,
    *,
    render_json,
    render_text,
    render_markdown,
    labels,
) -> None:
    """Print TLOCK/TTIMEOUT analysis in requested formats."""
    if output in (OutputType.json, OutputType.both):
        console.print(render_json(result, labels=labels))
    if output in (OutputType.markdown, OutputType.both):
        if output == OutputType.both:
            console.print("\n" + "=" * 40 + " MARKDOWN " + "=" * 40 + "\n")
        console.print(render_markdown(result, labels=labels))
    if output in (OutputType.text, OutputType.both):
        if output == OutputType.both:
            console.print("\n" + "=" * 40 + " TEXT " + "=" * 40 + "\n")
        console.print(render_text(result, labels=labels))


def format_filter_summary(filters: QueryFilters, source: SourceType) -> str:
    parts = [f"Source={source.value}"]
    if filters.log_ids:
        parts.append(f"log_id={','.join(filters.log_ids)}")
    if filters.time_from or filters.time_to:
        parts.append(
            f"period={filters.time_from or '…'} .. {filters.time_to or '…'}"
        )
    else:
        parts.append("period=all")
    if filters.hosts:
        parts.append(f"hosts={','.join(filters.hosts)}")
    if filters.process_name:
        parts.append(f"database={filters.process_name}")
    if filters.file_like:
        parts.append(f"file_like={filters.file_like}")
    parts.append(f"min_duration={filters.min_duration_us / 1_000_000}s")
    return " ".join(parts)


def format_deadlock_filter_summary(
    filters: DeadlockQueryFilters, source: SourceType
) -> str:
    parts = [f"Source={source.value}"]
    if filters.log_ids:
        parts.append(f"log_id={','.join(filters.log_ids)}")
    if filters.time_from or filters.time_to:
        parts.append(
            f"period={filters.time_from or '…'} .. {filters.time_to or '…'}"
        )
    else:
        parts.append("period=all")
    if filters.hosts:
        parts.append(f"hosts={','.join(filters.hosts)}")
    if filters.process_name:
        parts.append(f"database={filters.process_name}")
    if filters.single_at:
        parts.append(f"at={filters.single_at}")
    return " ".join(parts)
