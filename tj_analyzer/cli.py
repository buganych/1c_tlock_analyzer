"""Unified CLI: TLOCK + TTIMEOUT + TDEADLOCK in one run."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from tj_common.analysis.unified_pipeline import (
    ALL_ANALYZERS,
    AnalyzerKind,
    run_unified_analysis,
)
from tj_common.cli_shared import (
    OutputType,
    SourceType,
    build_clickhouse_source,
    build_deadlock_clickhouse_source,
    build_deadlock_filters,
    build_filters,
    format_filter_summary,
    make_analysis_progress,
    print_report_paths,
    write_unified_analysis_reports,
)
from tj_common.report.unified import render_unified_json, render_unified_text
from tj_common.sources.unified_file import (
    load_unified_json_file,
    load_unified_plain_file,
)
from tj_common.utils import apply_mcp_clickhouse_env

app = typer.Typer(
    help="Analyze all 1C lock problems: TLOCK waits, TTIMEOUT, TDEADLOCK (one command)"
)
console = Console()


def _parse_only(value: Optional[str]) -> list[AnalyzerKind]:
    if not value:
        return list(ALL_ANALYZERS)
    mapping = {k.value: k for k in AnalyzerKind}
    kinds: list[AnalyzerKind] = []
    for part in value.split(","):
        key = part.strip().lower()
        if key in mapping:
            kinds.append(mapping[key])
        elif key:
            raise typer.BadParameter(
                f"Unknown analyzer {part!r}. Use: tlock, ttimeout, tdeadlock"
            )
    return kinds or list(ALL_ANALYZERS)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    source: SourceType = typer.Option(SourceType.click, help="Log source"),
    log_id: Optional[str] = typer.Option(
        None, "--log-id", help="Log stream id(s); required for click"
    ),
    time_from: Optional[str] = typer.Option(None, "--from", help="Start time (ISO)"),
    time_to: Optional[str] = typer.Option(None, "--to", help="End time (ISO)"),
    min_duration: float = typer.Option(
        0.0, "--min-duration", help="Min wait duration (TLOCK/TTIMEOUT), seconds"
    ),
    agent_chunk_size: int = typer.Option(
        1000,
        "--agent-chunk-size",
        help="Victims per parallel agent (0 = sequential only)",
    ),
    hosts: Optional[str] = typer.Option(None, help="Comma-separated hosts"),
    database: Optional[str] = typer.Option(
        None, "--database", help="ProcessName filter (AND with log_id)"
    ),
    file_like: Optional[str] = typer.Option(
        None,
        "--file-like",
        help="ClickHouse only: optional file LIKE pattern, e.g. %tlock_1607235%",
    ),
    file: Optional[str] = typer.Option(None, help="TJ file for plain/json"),
    base_date: Optional[str] = typer.Option(None, help="Base date for plain TJ"),
    only: Optional[str] = typer.Option(
        None,
        "--only",
        help="Comma-separated subset: tlock,ttimeout,tdeadlock (default: all)",
    ),
    at: Optional[str] = typer.Option(
        None, "--at", help="Single TDEADLOCK timestamp (only affects tdeadlock)"
    ),
    connect_id: Optional[str] = typer.Option(None, "--connect-id"),
    session_id: Optional[str] = typer.Option(None, "--session-id"),
    host: Optional[str] = typer.Option(None, "--host", help="Host for TDEADLOCK --at mode"),
    clickhouse_host: Optional[str] = typer.Option(None, "--clickhouse-host"),
    clickhouse_port: Optional[int] = typer.Option(None, "--clickhouse-port"),
    clickhouse_user: Optional[str] = typer.Option(None, "--clickhouse-user"),
    clickhouse_password: Optional[str] = typer.Option(None, "--clickhouse-password"),
    clickhouse_db: Optional[str] = typer.Option(None, "--clickhouse-db"),
    config_catalog: Optional[str] = typer.Option(
        None, "--config-catalog", help="1C config export for TDEADLOCK context trees"
    ),
    output: OutputType = typer.Option(OutputType.both, "--output"),
    report_dir: Optional[str] = typer.Option(
        None,
        "--report-dir",
        help="Write analysis.json, analysis.md, analysis.html to this directory",
    ),
):
    """Run TLOCK, TTIMEOUT, and TDEADLOCK analysis with shared filters."""
    if ctx.invoked_subcommand is not None:
        return

    apply_mcp_clickhouse_env()

    kinds = _parse_only(only)
    tlock_filters = build_filters(
        log_id, time_from, time_to, min_duration, hosts, database, source, file_like
    )
    ttimeout_filters = tlock_filters
    tdeadlock_filters = build_deadlock_filters(
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

    tlock_src = ttimeout_src = None
    tdeadlock_src = None

    if source == SourceType.click:
        ch_kw = dict(
            ch_host=clickhouse_host,
            ch_port=clickhouse_port,
            ch_user=clickhouse_user,
            ch_password=clickhouse_password,
            ch_database=clickhouse_db,
        )
        if AnalyzerKind.tlock in kinds:
            tlock_src = build_clickhouse_source(
                **ch_kw, victim_table="tj_tlock", victim_event="TLOCK"
            )
        if AnalyzerKind.ttimeout in kinds:
            ttimeout_src = build_clickhouse_source(
                **ch_kw, victim_table="tj_ttimeout", victim_event="TTIMEOUT"
            )
        if AnalyzerKind.tdeadlock in kinds:
            tdeadlock_src = build_deadlock_clickhouse_source(**ch_kw)
        console.print(
            f"[dim]{format_filter_summary(tlock_filters, source)}[/dim]"
        )
        if database:
            console.print(f"[dim]database filter: {database}[/dim]")
    else:
        if not file:
            raise typer.BadParameter("--file is required for plain/json")
        from tj_common.utils import parse_datetime

        bd = parse_datetime(base_date) if base_date else None
        if source == SourceType.plain:
            tlock_src, ttimeout_src, tdeadlock_src = load_unified_plain_file(
                file, base_date=bd
            )
        else:
            tlock_src, ttimeout_src, tdeadlock_src = load_unified_json_file(file)
        console.print(f"[dim]Source={source.value} file={file}[/dim]")

    result = run_unified_analysis(
        kinds=kinds,
        tlock_source=tlock_src,
        ttimeout_source=ttimeout_src,
        tdeadlock_source=tdeadlock_src,
        tlock_filters=tlock_filters if AnalyzerKind.tlock in kinds else None,
        ttimeout_filters=ttimeout_filters if AnalyzerKind.ttimeout in kinds else None,
        tdeadlock_filters=tdeadlock_filters if AnalyzerKind.tdeadlock in kinds else None,
        config_catalog=config_catalog,
        progress=make_analysis_progress(
            console, "tj_analyzer", agent_chunk_size=agent_chunk_size
        ),
    )

    s = result.summary
    console.print(
        f"[green]TLOCK: {s['tlock_victims']}  "
        f"TTIMEOUT: {s['ttimeout_victims']}  "
        f"TDEADLOCK: {s['tdeadlock_cases']}[/green]"
    )
    if s["total_errors"]:
        console.print(f"[yellow]Errors: {s['total_errors']}[/yellow]")

    meta = format_filter_summary(tlock_filters, source)

    if report_dir:
        paths = write_unified_analysis_reports(
            report_dir,
            result,
            log_ids=tlock_filters.log_ids,
            database=database,
            meta=meta,
        )
        print_report_paths(console, paths)
    else:
        if output in (OutputType.json, OutputType.both):
            console.print(render_unified_json(result))
        if output in (OutputType.text, OutputType.both):
            if output == OutputType.both:
                console.print("\n" + "=" * 40 + " TEXT REPORT " + "=" * 40 + "\n")
            console.print(render_unified_text(result))


def app_entry():
    app()


if __name__ == "__main__":
    app()
