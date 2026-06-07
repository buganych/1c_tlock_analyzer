"""CLI entry point for CALL analysis."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from tj_common.analysis.call_pipeline import (
    CallAnalysisOptions,
    run_call_analysis_clickhouse,
    run_call_analysis_json_file,
    run_call_analysis_plain_file,
)
from tj_common.analysis.progress import AnalysisProgress
from tj_common.cli_shared import OutputType, SourceType, parse_csv, print_report_paths
from tj_common.models_call import CallQueryFilters
from tj_common.report.call_html import render_call_html
from tj_common.report.call_json import render_call_json
from tj_common.report.call_markdown import render_call_markdown
from tj_common.report.write import resolve_report_dir, write_triple_reports
from tj_common.sources.call_clickhouse import CallClickHouseSource
from tj_common.utils import apply_mcp_clickhouse_env, clickhouse_config_from_env, parse_datetime

app = typer.Typer(help="Analyze 1C CALL events (duration, CPU, memory, disk tops)")
console = Console()


def _build_call_filters(
    log_id: Optional[str],
    time_from: Optional[str],
    time_to: Optional[str],
    min_duration: float,
    hosts: Optional[str],
    database: Optional[str],
    source: SourceType,
    file_like: Optional[str],
) -> CallQueryFilters:
    log_ids = parse_csv(log_id)
    if source == SourceType.click and not log_ids:
        raise typer.BadParameter(
            "For --source click specify --log-id (comma-separated)."
        )
    t_from = parse_datetime(time_from) if time_from else None
    t_to = parse_datetime(time_to) if time_to else None
    if t_from and t_to and t_from >= t_to:
        raise typer.BadParameter("--from must be earlier than --to")
    pattern = (file_like or "").strip() or None
    if pattern and source != SourceType.click:
        raise typer.BadParameter("--file-like applies only to --source click")
    return CallQueryFilters(
        log_ids=log_ids,
        time_from=t_from,
        time_to=t_to,
        min_duration_us=int(min_duration * 1_000_000),
        hosts=parse_csv(hosts),
        process_name=database,
        file_like=pattern,
    )


def _format_call_filter_summary(filters: CallQueryFilters, source: SourceType) -> dict:
    summary = {"source": source.value}
    if filters.log_ids:
        summary["log_id"] = ",".join(filters.log_ids)
    summary["period"] = (
        f"{filters.time_from or '…'} .. {filters.time_to or '…'}"
        if filters.time_from or filters.time_to
        else "all"
    )
    if filters.hosts:
        summary["hosts"] = ",".join(filters.hosts)
    if filters.process_name:
        summary["database"] = filters.process_name
    if filters.file_like:
        summary["file_like"] = filters.file_like
    summary["min_duration_sec"] = filters.min_duration_us / 1_000_000
    return summary


def _write_call_reports(
    report_dir: str,
    result,
    *,
    log_ids: list[str] | None,
    database: str | None,
    meta: str,
) -> dict:
    directory = resolve_report_dir(
        report_dir,
        log_ids=log_ids,
        database=database,
        analyzer="call_analyzer",
    )
    return write_triple_reports(
        directory,
        json_body=render_call_json(result),
        md_body=render_call_markdown(result),
        html_body=render_call_html(result, meta=meta),
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    source: SourceType = typer.Option(SourceType.click, help="Log source type"),
    log_id: Optional[str] = typer.Option(
        None,
        "--log-id",
        help="Log stream id(s) in ClickHouse (comma-separated)",
    ),
    time_from: Optional[str] = typer.Option(None, "--from", help="Start time (ISO)"),
    time_to: Optional[str] = typer.Option(None, "--to", help="End time (ISO)"),
    min_duration: float = typer.Option(
        0.0, "--min-duration", help="Min CALL duration in seconds"
    ),
    hosts: Optional[str] = typer.Option(None, help="Comma-separated host names"),
    database: Optional[str] = typer.Option(
        None, "--database", help="Optional ProcessName / IB filter"
    ),
    file_like: Optional[str] = typer.Option(
        None, "--file-like", help="ClickHouse file LIKE pattern"
    ),
    file: Optional[str] = typer.Option(None, help="Path to TJ file (plain/json)"),
    base_date: Optional[str] = typer.Option(
        None, help="Base date for plain TJ (time-only lines)"
    ),
    top: int = typer.Option(
        20,
        "--top",
        help="Visible rows per table; rest in collapsible section",
    ),
    chunk_size: int = typer.Option(
        50_000,
        "--chunk-size",
        help="Events per portion for parallel processing",
    ),
    parallel_workers: int = typer.Option(
        4,
        "--parallel-workers",
        help="Max parallel workers for large datasets",
    ),
    clickhouse_host: Optional[str] = typer.Option(None, "--clickhouse-host"),
    clickhouse_port: Optional[int] = typer.Option(None, "--clickhouse-port"),
    clickhouse_user: Optional[str] = typer.Option(None, "--clickhouse-user"),
    clickhouse_password: Optional[str] = typer.Option(None, "--clickhouse-password"),
    clickhouse_db: Optional[str] = typer.Option(None, "--clickhouse-db"),
    output: OutputType = typer.Option(OutputType.both, "--output"),
    report_dir: Optional[str] = typer.Option(
        None,
        "--report-dir",
        help="Write analysis.json, analysis.md, analysis.html",
    ),
):
    """Aggregate CALL events into TOP tables by duration, CPU, memory, and disk."""
    if ctx.invoked_subcommand is not None:
        return

    apply_mcp_clickhouse_env()
    filters = _build_call_filters(
        log_id, time_from, time_to, min_duration, hosts, database, source, file_like
    )
    filters_summary = _format_call_filter_summary(filters, source)
    meta = " ".join(f"{k}={v}" for k, v in filters_summary.items())

    progress = AnalysisProgress(
        label="CALL",
        emit=lambda msg: console.print(f"[cyan]{msg}[/cyan]"),
    )
    options = CallAnalysisOptions(
        visible_rows=top,
        chunk_size=chunk_size,
        parallel_workers=parallel_workers,
        progress=progress,
    )

    if source == SourceType.click:
        cfg = clickhouse_config_from_env()
        ch = CallClickHouseSource(
            host=clickhouse_host or cfg["host"],
            port=clickhouse_port or cfg["port"],
            username=clickhouse_user or cfg["username"],
            password=clickhouse_password if clickhouse_password is not None else cfg["password"],
            database=clickhouse_db or cfg["database"],
            secure=cfg["secure"],
        )
        result = run_call_analysis_clickhouse(
            ch,
            filters,
            options=options,
            filters_summary=filters_summary,
        )
    elif source == SourceType.plain:
        if not file:
            raise typer.BadParameter("--file is required for plain source")
        bd = parse_datetime(base_date) if base_date else None
        result = run_call_analysis_plain_file(
            file,
            filters,
            base_date=bd,
            options=options,
            filters_summary=filters_summary,
        )
    else:
        if not file:
            raise typer.BadParameter("--file is required for json source")
        result = run_call_analysis_json_file(
            file,
            filters,
            options=options,
            filters_summary=filters_summary,
        )

    if report_dir:
        paths = _write_call_reports(
            report_dir,
            result,
            log_ids=filters.log_ids,
            database=filters.process_name,
            meta=meta,
        )
        print_report_paths(console, paths)

    if output in (OutputType.json, OutputType.both):
        console.print(render_call_json(result))
    if output in (OutputType.markdown, OutputType.both):
        if output == OutputType.both:
            console.print("\n" + "=" * 40 + " MARKDOWN " + "=" * 40 + "\n")
        console.print(render_call_markdown(result))


def app_entry() -> None:
    app()


if __name__ == "__main__":
    app_entry()
