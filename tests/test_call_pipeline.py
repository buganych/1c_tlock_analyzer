"""Tests for chunked CALL pipeline helpers."""

from datetime import datetime, timedelta

from tj_common.sources.call_clickhouse import split_time_windows


def test_split_time_windows_count():
    start = datetime(2026, 6, 4, 10, 0, 0)
    end = start + timedelta(hours=2)
    windows = split_time_windows(start, end, num_chunks=4)
    assert len(windows) == 4
    assert windows[0][0] is None
    assert windows[-1][1] is None
    assert windows[1][0] == windows[0][1]


def test_split_time_windows_single_chunk():
    ts = datetime(2026, 6, 4, 10, 0, 0)
    assert split_time_windows(ts, ts, num_chunks=3) == [(None, None)]
