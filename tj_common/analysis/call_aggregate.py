"""Aggregate CALL events into grouped tables with merge support for chunked processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from tj_common.call_context import resolve_call_event_context
from tj_common.models_call import CallEvent, CallTopRow

US_PER_SEC = 1_000_000
BYTES_PER_MB = 1024 * 1024


@dataclass
class MetricStats:
    count: int = 0
    sum_val: int = 0
    max_val: int = 0
    min_val: int = 0

    @property
    def avg_int(self) -> int:
        if self.count == 0:
            return 0
        return round(self.sum_val / self.count)

    def add(self, value: int) -> None:
        if self.count == 0:
            self.min_val = value
            self.max_val = value
        self.count += 1
        self.sum_val += value
        self.max_val = max(self.max_val, value)
        self.min_val = min(self.min_val, value)

    def merge(self, other: MetricStats) -> None:
        if other.count == 0:
            return
        if self.count == 0:
            self.count = other.count
            self.sum_val = other.sum_val
            self.max_val = other.max_val
            self.min_val = other.min_val
            return
        self.count += other.count
        self.sum_val += other.sum_val
        self.max_val = max(self.max_val, other.max_val)
        self.min_val = min(self.min_val, other.min_val)


@dataclass
class CallAggregateBuckets:
    duration: dict[str, MetricStats]
    cpu: dict[str, MetricStats]
    memory: dict[str, MetricStats]
    disk_in: dict[str, MetricStats]
    disk_out: dict[str, MetricStats]
    disk_total: dict[str, MetricStats]
    total_events: int = 0

    @classmethod
    def empty(cls) -> CallAggregateBuckets:
        return cls(
            duration={},
            cpu={},
            memory={},
            disk_in={},
            disk_out={},
            disk_total={},
            total_events=0,
        )

    def merge(self, other: CallAggregateBuckets) -> None:
        self.total_events += other.total_events
        _merge_metric_dict(self.duration, other.duration)
        _merge_metric_dict(self.cpu, other.cpu)
        _merge_metric_dict(self.memory, other.memory)
        _merge_metric_dict(self.disk_in, other.disk_in)
        _merge_metric_dict(self.disk_out, other.disk_out)
        _merge_metric_dict(self.disk_total, other.disk_total)


def _merge_metric_dict(
    target: dict[str, MetricStats], source: dict[str, MetricStats]
) -> None:
    for ctx, stats in source.items():
        if ctx not in target:
            target[ctx] = MetricStats()
        target[ctx].merge(stats)


def aggregate_call_events(events: Iterable[CallEvent]) -> CallAggregateBuckets:
    buckets = CallAggregateBuckets.empty()
    for event in events:
        buckets.total_events += 1
        ctx = resolve_call_event_context(event)
        _add_metric(buckets.duration, ctx, event.duration_us)
        _add_metric(buckets.cpu, ctx, event.cpu_time_us)
        _add_metric(buckets.memory, ctx, event.memory_peak)
        _add_metric(buckets.disk_in, ctx, event.in_bytes)
        _add_metric(buckets.disk_out, ctx, event.out_bytes)
        _add_metric(buckets.disk_total, ctx, event.in_bytes + event.out_bytes)
    return buckets


def _add_metric(store: dict[str, MetricStats], ctx: str, value: int) -> None:
    if ctx not in store:
        store[ctx] = MetricStats()
    store[ctx].add(value)


def _us_to_sec_row(ctx: str, stats: MetricStats) -> CallTopRow:
    return CallTopRow(
        context=ctx,
        count=stats.count,
        avg=round(stats.avg_int / US_PER_SEC),
        max=round(stats.max_val / US_PER_SEC),
        min=round(stats.min_val / US_PER_SEC),
        total=round(stats.sum_val / US_PER_SEC),
    )


def _bytes_to_mb_row(ctx: str, stats: MetricStats) -> CallTopRow:
    return CallTopRow(
        context=ctx,
        count=stats.count,
        avg=round(stats.avg_int / BYTES_PER_MB),
        max=round(stats.max_val / BYTES_PER_MB),
        min=round(stats.min_val / BYTES_PER_MB),
        total=round(stats.sum_val / BYTES_PER_MB),
    )


def metric_stats_to_rows(
    stats: dict[str, MetricStats],
    *,
    to_row: Callable[[str, MetricStats], CallTopRow],
    sort_key: Callable[[CallTopRow], int] | None = None,
) -> list[CallTopRow]:
    rows = [to_row(ctx, s) for ctx, s in stats.items() if s.count > 0]
    key = sort_key or (lambda r: r.avg)
    rows.sort(key=key, reverse=True)
    return rows


def buckets_to_result(
    buckets: CallAggregateBuckets,
    *,
    filters_summary: dict,
    visible_rows: int = 20,
) -> "CallAnalysisResult":
    from tj_common.models_call import CallAnalysisResult

    return CallAnalysisResult(
        duration_rows=metric_stats_to_rows(buckets.duration, to_row=_us_to_sec_row),
        cpu_rows=metric_stats_to_rows(buckets.cpu, to_row=_us_to_sec_row),
        memory_rows=metric_stats_to_rows(buckets.memory, to_row=_bytes_to_mb_row),
        disk_total_rows=metric_stats_to_rows(buckets.disk_total, to_row=_bytes_to_mb_row),
        disk_in_rows=metric_stats_to_rows(buckets.disk_in, to_row=_bytes_to_mb_row),
        disk_out_rows=metric_stats_to_rows(buckets.disk_out, to_row=_bytes_to_mb_row),
        total_events=buckets.total_events,
        filters_summary=filters_summary,
        visible_rows=visible_rows,
    )


def stats_from_sql_row(
    *,
    count: int,
    avg_val: float,
    max_val: float,
    min_val: float,
) -> MetricStats:
    return MetricStats(
        count=count,
        sum_val=int(round(avg_val * count)),
        max_val=int(round(max_val)),
        min_val=int(round(min_val)),
    )
