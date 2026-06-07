"""ClickHouse adapter for tj_call aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import clickhouse_connect

from tj_common.analysis.call_aggregate import (
    CallAggregateBuckets,
    MetricStats,
    stats_from_sql_row,
)
from tj_common.call_context import CONTEXT_SQL_EXPR
from tj_common.models_call import CallQueryFilters
from tj_common.utils import host_variants


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
        tzinfo=None
    )


class CallClickHouseSource:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "onec_logs",
        secure: bool = False,
    ):
        self.database = database
        self._connect_host = host
        self._connect_port = port
        self._connect_username = username
        self._connect_password = password
        self._connect_secure = secure
        self.client = clickhouse_connect.get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            secure=secure,
        )

    @staticmethod
    def _ts_literal(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")

    def _query(self, sql: str, params: dict | None = None) -> list[dict]:
        result = self.client.query(sql, parameters=params or {})
        cols = result.column_names
        return [dict(zip(cols, row)) for row in result.result_rows]

    def _query_ts(
        self, sql_template: str, *, time_params: dict[str, datetime], params: dict | None = None
    ) -> list[dict]:
        merged = dict(params or {})
        for key, dt in time_params.items():
            merged[key] = self._ts_literal(dt)
        sql = sql_template
        for key in time_params:
            sql = sql.replace(f"{{{key}:DateTime64(6)}}", f"{{{key}:String}}")
        return self._query(sql, merged)

    def _host_clause(self, hosts: list[str] | None) -> tuple[str, dict]:
        variants = host_variants(hosts)
        if not variants:
            return "1=1", {}
        placeholders = ", ".join(f"{{{f'h{i}'}:String}}" for i in range(len(variants)))
        params = {f"h{i}": v for i, v in enumerate(variants)}
        return f"computer_name IN ({placeholders})", params

    def _log_id_clause(self, log_ids: list[str] | None) -> tuple[str, dict]:
        if not log_ids:
            return "1=1", {}
        placeholders = ", ".join(f"{{{f'lid{i}'}:String}}" for i in range(len(log_ids)))
        params = {f"lid{i}": v for i, v in enumerate(log_ids)}
        return f"log_id IN ({placeholders})", params

    def _file_like_clause(self, file_like: str | None) -> tuple[str, dict]:
        if not file_like:
            return "1=1", {}
        return "file LIKE {file_like:String}", {"file_like": file_like}

    def _time_clause(
        self,
        time_from: datetime | None,
        time_to: datetime | None,
        *,
        column: str = "ts",
    ) -> tuple[str, dict[str, datetime], bool]:
        parts: list[str] = []
        time_params: dict[str, datetime] = {}
        if time_from is not None:
            parts.append(f"{column} > {{time_from:DateTime64(6)}}")
            time_params["time_from"] = time_from
        if time_to is not None:
            parts.append(f"{column} <= {{time_to:DateTime64(6)}}")
            time_params["time_to"] = time_to
        if not parts:
            return "1=1", {}, False
        return " AND ".join(parts), time_params, True

    def _where_parts(
        self,
        filters: CallQueryFilters,
        *,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> tuple[str, dict[str, Any], dict[str, datetime], bool]:
        log_sql, log_params = self._log_id_clause(filters.log_ids)
        host_sql, host_params = self._host_clause(filters.hosts)
        file_sql, file_params = self._file_like_clause(filters.file_like)
        t_from = time_from if time_from is not None else filters.time_from
        t_to = time_to if time_to is not None else filters.time_to
        time_sql, time_params, use_time = self._time_clause(t_from, t_to)

        where = f"""
            duration >= {{min_duration:UInt64}}
            AND {log_sql}
            AND {host_sql}
            AND {file_sql}
            AND {time_sql}
        """
        params: dict[str, Any] = {
            "min_duration": filters.min_duration_us,
            **log_params,
            **host_params,
            **file_params,
        }
        if filters.process_name:
            where += " AND lower(process_name) = lower({process_name:String})"
            params["process_name"] = filters.process_name
        return where, params, time_params, use_time

    def _run_where_query(
        self,
        sql: str,
        params: dict[str, Any],
        time_params: dict[str, datetime],
        use_time: bool,
    ) -> list[dict]:
        if use_time:
            return self._query_ts(sql, time_params=time_params, params=params)
        return self._query(sql, params)

    def count_events(self, filters: CallQueryFilters) -> int:
        where, params, time_params, use_time = self._where_parts(filters)
        sql = f"""
            SELECT count() AS cnt
            FROM {self.database}.tj_call
            WHERE {where}
        """
        rows = self._run_where_query(sql, params, time_params, use_time)
        return int(rows[0]["cnt"]) if rows else 0

    def fetch_time_bounds(
        self, filters: CallQueryFilters
    ) -> tuple[datetime | None, datetime | None]:
        where, params, time_params, use_time = self._where_parts(filters)
        sql = f"""
            SELECT min(ts) AS min_ts, max(ts) AS max_ts
            FROM {self.database}.tj_call
            WHERE {where}
        """
        rows = self._run_where_query(sql, params, time_params, use_time)
        if not rows or rows[0]["min_ts"] is None:
            return None, None
        return _parse_ts(rows[0]["min_ts"]), _parse_ts(rows[0]["max_ts"])

    def aggregate_chunk(
        self,
        filters: CallQueryFilters,
        *,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
    ) -> CallAggregateBuckets:
        where, params, time_params, use_time = self._where_parts(
            filters, time_from=time_from, time_to=time_to
        )
        ctx = CONTEXT_SQL_EXPR
        base_from = f"""
            FROM (
              SELECT {ctx} AS ctx, duration, cpu_time, memory_peak, in_bytes, out_bytes
              FROM {self.database}.tj_call
              WHERE {where}
            )
        """
        buckets = CallAggregateBuckets.empty()

        metric_sql = """
            SELECT ctx, count() AS cnt,
                   avg({col}) AS avg_val,
                   max({col}) AS max_val,
                   min({col}) AS min_val
            {base_from}
            GROUP BY ctx
        """
        duration_sql = metric_sql.format(col="duration", base_from=base_from)
        cpu_sql = metric_sql.format(col="cpu_time", base_from=base_from)
        memory_sql = metric_sql.format(col="memory_peak", base_from=base_from)
        disk_in_sql = metric_sql.format(col="in_bytes", base_from=base_from)
        disk_out_sql = metric_sql.format(col="out_bytes", base_from=base_from)
        disk_total_sql = metric_sql.format(
            col="in_bytes + out_bytes", base_from=base_from
        )
        count_sql = f"""
            SELECT count() AS cnt
            FROM {self.database}.tj_call
            WHERE {where}
        """

        def run(sql: str) -> list[dict]:
            return self._run_where_query(sql, params, time_params, use_time)

        count_rows = run(count_sql)
        buckets.total_events = int(count_rows[0]["cnt"]) if count_rows else 0

        def load_metric(rows: list[dict]) -> dict[str, MetricStats]:
            out: dict[str, MetricStats] = {}
            for row in rows:
                cnt = int(row["cnt"])
                out[str(row["ctx"])] = stats_from_sql_row(
                    count=cnt,
                    avg_val=float(row["avg_val"]),
                    max_val=float(row["max_val"]),
                    min_val=float(row["min_val"]),
                )
            return out

        buckets.duration = load_metric(run(duration_sql))
        buckets.cpu = load_metric(run(cpu_sql))
        buckets.memory = load_metric(run(memory_sql))
        buckets.disk_in = load_metric(run(disk_in_sql))
        buckets.disk_out = load_metric(run(disk_out_sql))
        buckets.disk_total = load_metric(run(disk_total_sql))
        return buckets

    def clone(self) -> CallClickHouseSource:
        return CallClickHouseSource(
            host=self._connect_host,
            port=self._connect_port,
            username=self._connect_username,
            password=self._connect_password,
            database=self.database,
            secure=self._connect_secure,
        )


def split_time_windows(
    min_ts: datetime,
    max_ts: datetime,
    *,
    num_chunks: int,
) -> list[tuple[datetime | None, datetime | None]]:
    """Split [min_ts, max_ts] into contiguous windows (inclusive end per chunk)."""
    if num_chunks <= 1 or min_ts >= max_ts:
        return [(None, None)]
    total = (max_ts - min_ts).total_seconds()
    step = total / num_chunks
    windows: list[tuple[datetime | None, datetime | None]] = []
    prev_end = min_ts
    for i in range(num_chunks):
        if i == 0:
            start = None
        else:
            start = prev_end
        if i == num_chunks - 1:
            end = None
        else:
            end = min_ts + timedelta(seconds=step * (i + 1))
            prev_end = end
        windows.append((start, end))
    return windows
