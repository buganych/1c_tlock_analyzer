"""CALL analysis pipeline with parallel chunked processing."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from tj_common.analysis.call_aggregate import (
    CallAggregateBuckets,
    aggregate_call_events,
    buckets_to_result,
)
from tj_common.analysis.progress import AnalysisProgress, ProgressTracker, should_report_progress
from tj_common.models_call import CallAnalysisResult, CallQueryFilters
from tj_common.sources.call_clickhouse import CallClickHouseSource, split_time_windows
from tj_common.sources.call_file import iter_json_call_chunks, iter_plain_call_chunks

DEFAULT_CHUNK_SIZE = 50_000
DEFAULT_PARALLEL_WORKERS = 4
PARALLEL_THRESHOLD = 10_000


@dataclass
class CallAnalysisOptions:
    visible_rows: int = 20
    chunk_size: int = DEFAULT_CHUNK_SIZE
    parallel_workers: int = DEFAULT_PARALLEL_WORKERS
    progress: AnalysisProgress | None = None


class CallSource(Protocol):
    def count_events(self, filters: CallQueryFilters) -> int: ...
    def aggregate_chunk(
        self,
        filters: CallQueryFilters,
        *,
        time_from=None,
        time_to=None,
    ) -> CallAggregateBuckets: ...
    def fetch_time_bounds(
        self, filters: CallQueryFilters
    ) -> tuple[object | None, object | None]: ...
    def clone(self) -> CallSource: ...


def _emit(progress: AnalysisProgress | None, msg: str) -> None:
    if progress and progress.emit:
        progress.emit(msg)


def _process_chunks_parallel(
    chunks: list[tuple[object | None, object | None]],
    *,
    source: CallSource,
    filters: CallQueryFilters,
    workers: int,
    progress: AnalysisProgress | None,
    label: str,
) -> CallAggregateBuckets:
    merged = CallAggregateBuckets.empty()
    total = len(chunks)
    tracker: ProgressTracker | None = None
    if should_report_progress(total, progress):
        tracker = ProgressTracker(
            total,
            label=label,
            status_interval_sec=progress.status_interval_sec if progress else 10.0,
            emit=progress.emit if progress else None,
        )

    def work(window: tuple[object | None, object | None], idx: int) -> CallAggregateBuckets:
        worker_source = source.clone()
        t_from, t_to = window
        _emit(
            progress,
            f"[{label}] порция {idx + 1}/{total}: агрегация"
            + (f" {t_from} .. {t_to}" if t_from or t_to else ""),
        )
        return worker_source.aggregate_chunk(filters, time_from=t_from, time_to=t_to)

    max_workers = min(workers, total)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(work, window, idx): idx for idx, window in enumerate(chunks)
        }
        for future in as_completed(futures):
            try:
                part = future.result()
                merged.merge(part)
                if tracker:
                    tracker.tick()
            except Exception:
                if tracker:
                    tracker.tick(error=True)
                raise
    if tracker:
        tracker.finish()
    return merged


def _aggregate_clickhouse(
    source: CallClickHouseSource,
    filters: CallQueryFilters,
    options: CallAnalysisOptions,
) -> CallAggregateBuckets:
    label = options.progress.label if options.progress else "CALL"
    total = source.count_events(filters)
    if total == 0:
        return CallAggregateBuckets.empty()

    chunk_size = max(1, options.chunk_size)
    workers = max(1, options.parallel_workers)
    use_parallel = total > PARALLEL_THRESHOLD and workers > 1

    if not use_parallel or total <= chunk_size:
        _emit(options.progress, f"[{label}] агрегация {total} событий (одна порция)")
        return source.aggregate_chunk(filters)

    num_chunks = min(workers, max(2, math.ceil(total / chunk_size)))
    min_ts, max_ts = source.fetch_time_bounds(filters)
    if min_ts is None or max_ts is None:
        return source.aggregate_chunk(filters)

    windows = split_time_windows(min_ts, max_ts, num_chunks=num_chunks)
    _emit(
        options.progress,
        f"[{label}] {total} событий: {len(windows)} порций, "
        f"до {workers} параллельных агентов",
    )
    return _process_chunks_parallel(
        windows,
        source=source,
        filters=filters,
        workers=workers,
        progress=options.progress,
        label=label,
    )


def _aggregate_file_chunks(
    chunk_iter: Iterator[list],
    options: CallAnalysisOptions,
) -> CallAggregateBuckets:
    label = options.progress.label if options.progress else "CALL"
    chunks = list(chunk_iter)
    if not chunks:
        return CallAggregateBuckets.empty()

    total_events = sum(len(c) for c in chunks)
    workers = max(1, options.parallel_workers)
    use_parallel = len(chunks) > 1 and total_events > PARALLEL_THRESHOLD

    if not use_parallel:
        _emit(
            options.progress,
            f"[{label}] агрегация {total_events} событий из файла",
        )
        merged = CallAggregateBuckets.empty()
        for chunk in chunks:
            part = aggregate_call_events(chunk)
            merged.merge(part)
        return merged

    _emit(
        options.progress,
        f"[{label}] файл: {total_events} событий, {len(chunks)} порций, "
        f"до {workers} параллельных агентов",
    )

    merged = CallAggregateBuckets.empty()
    tracker: ProgressTracker | None = None
    if should_report_progress(len(chunks), options.progress):
        tracker = ProgressTracker(
            len(chunks),
            label=label,
            status_interval_sec=options.progress.status_interval_sec if options.progress else 10.0,
            emit=options.progress.emit if options.progress else None,
        )

    def work(events: list) -> CallAggregateBuckets:
        return aggregate_call_events(events)

    max_workers = min(workers, len(chunks))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(work, chunk) for chunk in chunks]
        for future in as_completed(futures):
            part = future.result()
            merged.merge(part)
            if tracker:
                tracker.tick()
    if tracker:
        tracker.finish()
    return merged


def run_call_analysis_clickhouse(
    source: CallClickHouseSource,
    filters: CallQueryFilters,
    *,
    options: CallAnalysisOptions | None = None,
    filters_summary: dict | None = None,
) -> CallAnalysisResult:
    opts = options or CallAnalysisOptions()
    buckets = _aggregate_clickhouse(source, filters, opts)
    return buckets_to_result(
        buckets,
        visible_rows=opts.visible_rows,
        filters_summary=filters_summary or {},
    )


def run_call_analysis_plain_file(
    path: str | Path,
    filters: CallQueryFilters,
    *,
    base_date,
    options: CallAnalysisOptions | None = None,
    filters_summary: dict | None = None,
) -> CallAnalysisResult:
    opts = options or CallAnalysisOptions()
    chunk_iter = iter_plain_call_chunks(
        path,
        base_date=base_date,
        filters=filters,
        chunk_size=max(1, opts.chunk_size),
    )
    buckets = _aggregate_file_chunks(chunk_iter, opts)
    return buckets_to_result(
        buckets,
        visible_rows=opts.visible_rows,
        filters_summary=filters_summary or {},
    )


def run_call_analysis_json_file(
    path: str | Path,
    filters: CallQueryFilters,
    *,
    options: CallAnalysisOptions | None = None,
    filters_summary: dict | None = None,
) -> CallAnalysisResult:
    opts = options or CallAnalysisOptions()
    chunk_iter = iter_json_call_chunks(
        path,
        filters=filters,
        chunk_size=max(1, opts.chunk_size),
    )
    buckets = _aggregate_file_chunks(chunk_iter, opts)
    return buckets_to_result(
        buckets,
        visible_rows=opts.visible_rows,
        filters_summary=filters_summary or {},
    )
