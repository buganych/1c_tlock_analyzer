"""Unit tests for CALL aggregation and merge."""

from datetime import datetime

from tj_common.analysis.call_aggregate import (
    CallAggregateBuckets,
    MetricStats,
    aggregate_call_events,
    buckets_to_result,
    metric_stats_to_rows,
    _bytes_to_mb_row,
    _us_to_sec_row,
)
from tj_common.models_call import CallEvent


def _event(
    ctx: str,
    duration_us: int,
    cpu_us: int = 0,
    mem: int = 0,
    in_b: int = 100,
    out_b: int = 50,
) -> CallEvent:
    module, _, method = ctx.partition(".")
    return CallEvent(
        ts=datetime(2026, 6, 4, 12, 0, 0),
        module=module,
        method=method,
        duration_us=duration_us,
        cpu_time_us=cpu_us,
        memory_peak=mem,
        in_bytes=in_b,
        out_bytes=out_b,
    )


def test_aggregate_call_events_basic():
    events = [
        _event("A.Run", 2_000_000, cpu_us=1_500_000, mem=1024),
        _event("A.Run", 4_000_000, cpu_us=2_500_000, mem=2048),
        _event("B.Go", 1_000_000, cpu_us=500_000, mem=512),
    ]
    buckets = aggregate_call_events(events)
    assert buckets.total_events == 3
    assert buckets.duration["A.Run"].count == 2
    assert buckets.duration["A.Run"].avg_int == 3_000_000
    assert buckets.cpu["A.Run"].avg_int == 2_000_000
    assert buckets.memory["B.Go"].max_val == 512


def test_merge_metric_stats_weighted_average():
    a = MetricStats(count=2, sum_val=6, max_val=4, min_val=2)
    b = MetricStats(count=1, sum_val=9, max_val=9, min_val=9)
    a.merge(b)
    assert a.count == 3
    assert a.avg_int == 5
    assert a.max_val == 9
    assert a.min_val == 2


def test_all_contexts_returned_not_truncated():
    events = [_event(f"C{i}.X", i * 1_000_000) for i in range(1, 26)]
    buckets = aggregate_call_events(events)
    rows = metric_stats_to_rows(buckets.duration, to_row=_us_to_sec_row)
    assert len(rows) == 25


def test_disk_three_tables_sorted_differently():
    mb = 1024 * 1024
    events = [
        _event("Write.Heavy", 1_000_000, in_b=3 * mb, out_b=mb // 10),
        _event("Read.Heavy", 1_000_000, in_b=mb // 10, out_b=3 * mb),
    ]
    buckets = aggregate_call_events(events)
    total = metric_stats_to_rows(buckets.disk_total, to_row=_bytes_to_mb_row)
    in_rows = metric_stats_to_rows(buckets.disk_in, to_row=_bytes_to_mb_row)
    out_rows = metric_stats_to_rows(buckets.disk_out, to_row=_bytes_to_mb_row)
    assert total[0].context == "Write.Heavy"
    assert in_rows[0].context == "Write.Heavy"
    assert out_rows[0].context == "Read.Heavy"


def test_buckets_to_result_integer_units():
    buckets = aggregate_call_events(
        [_event("Slow.Op", 10_000_000, cpu_us=8_000_000, mem=4_000_000)]
    )
    result = buckets_to_result(buckets, filters_summary={"source": "test"})
    assert result.total_events == 1
    assert result.duration_rows[0].context == "Slow.Op"
    assert result.duration_rows[0].avg == 10
    assert result.cpu_rows[0].avg == 8
    assert result.cpu_rows[0].total == 8
    assert result.memory_rows[0].avg == round(4_000_000 / (1024 * 1024))
    assert result.memory_rows[0].total == round(4_000_000 / (1024 * 1024))
    assert result.duration_rows[0].total == 10
    assert isinstance(result.duration_rows[0].avg, int)
