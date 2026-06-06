"""CLI for TDEADLOCK analyzer."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from tj_common.analysis.deadlock_pipeline import run_deadlock_analysis
from tj_common.cli_shared import (
    OutputType,
    SourceType,
    build_deadlock_clickhouse_source,
    build_deadlock_filters,
    format_deadlock_filter_summary,
)
from tj_common.report.deadlock_json import render_deadlock_json
from tj_common.report.deadlock_text import render_deadlock_text
from tj_common.sources.deadlock_plain import (
    load_deadlock_json_file,
    load_deadlock_plain_file,
)
from tj_common.utils import apply_mcp_clickhouse_env

app = typer.Typer(help="Analyze 1C TDEADLOCK events and build deadlock graphs")
console = Console()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    source: SourceType = typer.Option(SourceType.click, help="Log source type"),
    log_id: Optional[str] = typer.Option(
        None, "--log-id", help="Log stream id(s); required for click"
    ),
    time_from: Optional[str] = typer.Option(None, "--from", help="Start time (ISO)"),
    time_to: Optional[str] = typer.Option(None, "--to", help="End time (ISO)"),
    hosts: Optional[str] = typer.Option(None, help="Comma-separated hosts"),
    database: Optional[str] = typer.Option(
        None, "--database", help="Optional ProcessName filter (AND with log_id)"
    ),
    file: Optional[str] = typer.Option(None, help="TJ file for plain/json"),
    base_date: Optional[str] = typer.Option(None, help="Base date for plain TJ"),
    at: Optional[str] = typer.Option(
        None, "--at", help="Single TDEADLOCK timestamp (ISO)"
    ),
    connect_id: Optional[str] = typer.Option(
        None, "--connect-id", help="ConnectID for single-case mode"
    ),
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="SessionID for single-case mode"
    ),
    host: Optional[str] = typer.Option(
        None, "--host", help="Host filter for single-case mode"
    ),
    clickhouse_host: Optional[str] = typer.Option(None, "--clickhouse-host"),
    clickhouse_port: Optional[int] = typer.Option(None, "--clickhouse-port"),
    clickhouse_user: Optional[str] = typer.Option(None, "--clickhouse-user"),
    clickhouse_password: Optional[str] = typer.Option(None, "--clickhouse-password"),
    clickhouse_db: Optional[str] = typer.Option(None, "--clickhouse-db"),
    config_catalog: Optional[str] = typer.Option(
        None, "--config-catalog", help="Exported 1C config directory for source lookup"
    ),
    output: OutputType = typer.Option(OutputType.both, "--output"),
):
    """Analyze TDEADLOCK cases from ClickHouse or TJ files."""
    if ctx.invoked_subcommand is not None:
        return

    apply_mcp_clickhouse_env()

    filters = build_deadlock_filters(
        log_id,
        time_from,
        time_to,
        hosts or host,
        database,
        source,
        at=at,
        connect_id=connect_id,
        session_id=session_id,
    )

    if source == SourceType.click:
        log_source = build_deadlock_clickhouse_source(
            clickhouse_host,
            clickhouse_port,
            clickhouse_user,
            clickhouse_password,
            clickhouse_db,
        )
    else:
        if not file:
            raise typer.BadParameter("--file is required for plain/json")
        from tj_common.utils import parse_datetime

        bd = parse_datetime(base_date) if base_date else None
        if source == SourceType.plain:
            log_source = load_deadlock_plain_file(file, base_date=bd)
        else:
            log_source = load_deadlock_json_file(file)

    console.print(f"[dim]{format_deadlock_filter_summary(filters, source)}[/dim]")

    result = run_deadlock_analysis(
        log_source, filters, config_catalog=config_catalog
    )

    console.print(f"[green]Cases found: {len(result.cases)}[/green]")
    if result.errors:
        console.print(f"[yellow]Errors: {len(result.errors)}[/yellow]")

    if output in (OutputType.json, OutputType.both):
        console.print(render_deadlock_json(result))
    if output in (OutputType.text, OutputType.both):
        if output == OutputType.both:
            console.print("\n" + "=" * 40 + " TEXT REPORT " + "=" * 40 + "\n")
        console.print(render_deadlock_text(result))


def app_entry():
    app()


if __name__ == "__main__":
    app()
