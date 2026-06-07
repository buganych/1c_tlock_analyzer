"""ClickHouse onec_logs adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import clickhouse_connect

from tj_common.models import QueryFilters, TjEvent, TransactionBounds
from tj_common.sources.base import LogSource
from tj_common.utils import host_variants, pick_timeout_wait_tlock


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
        tzinfo=None
    )


def _row_to_victim(row: dict[str, Any], event_name: str) -> TjEvent:
    esc = str(row.get("escalating", "") or "").lower() == "true"
    return TjEvent(
        ts=_parse_ts(row["ts"]),
        event=event_name,
        connect_id=str(row.get("connect_id", "") or ""),
        wait_connections=str(row.get("wait_connections", "") or ""),
        regions=str(row.get("regions") or row.get("Regions") or ""),
        locks=str(row.get("locks") or row.get("Locks") or ""),
        duration_us=int(row.get("duration", 0) or 0),
        host=str(row.get("computer_name", "") or ""),
        process_name=str(row.get("process_name", "") or ""),
        user=str(row.get("usr", "") or ""),
        context=str(row.get("context", "") or ""),
        escalating=esc,
        application_name=str(row.get("application_name", "") or ""),
        log_id=str(row.get("log_id", "") or ""),
        raw=dict(row),
    )


class ClickHouseSource(LogSource):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "onec_logs",
        secure: bool = False,
        victim_table: str = "tj_tlock",
        victim_event: str = "TLOCK",
    ):
        self.database = database
        self.victim_table = victim_table
        self.victim_event = victim_event
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
        """Run query with datetime literals (clickhouse-connect DateTime64 params are unreliable)."""
        merged = dict(params or {})
        for key, dt in time_params.items():
            merged[key] = self._ts_literal(dt)
        sql = sql_template
        for key in time_params:
            sql = sql.replace(f"{{{key}:DateTime64(6)}}", f"{{{key}:String}}")
        return self._query(sql, merged)

    def _host_clause(self, hosts: list[str] | None, column: str = "computer_name") -> tuple[str, dict]:
        variants = host_variants(hosts)
        if not variants:
            return "1=1", {}
        placeholders = ", ".join(f"{{{f'h{i}'}:String}}" for i in range(len(variants)))
        params = {f"h{i}": v for i, v in enumerate(variants)}
        return f"{column} IN ({placeholders})", params

    def _log_id_clause(
        self, log_ids: list[str] | None, column: str = "log_id"
    ) -> tuple[str, dict]:
        if not log_ids:
            return "1=1", {}
        placeholders = ", ".join(f"{{{f'lid{i}'}:String}}" for i in range(len(log_ids)))
        params = {f"lid{i}": v for i, v in enumerate(log_ids)}
        return f"{column} IN ({placeholders})", params

    def _file_like_clause(
        self, file_like: str | None, column: str = "file"
    ) -> tuple[str, dict]:
        if not file_like:
            return "1=1", {}
        return f"{column} LIKE {{file_like:String}}", {"file_like": file_like}

    def _time_clause(
        self, time_from: datetime | None, time_to: datetime | None, column: str = "ts"
    ) -> tuple[str, dict[str, datetime], bool]:
        """Return SQL fragment, time params for _query_ts, and whether time filter is used."""
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

    def _victim_select_sql(self) -> str:
        """Victim table columns differ: tj_ttimeout has no regions/locks/escalating."""
        if self.victim_table == "tj_ttimeout":
            cols = (
                "log_id, ts, connect_id, wait_connections, duration, "
                "computer_name, process_name, usr, context, application_name"
            )
        else:
            cols = (
                "log_id, ts, connect_id, wait_connections, regions, locks, duration, "
                "computer_name, process_name, usr, context, escalating, application_name"
            )
        return cols

    def fetch_victims(self, filters: QueryFilters) -> list[TjEvent]:
        host_sql, host_params = self._host_clause(filters.hosts)
        log_sql, log_params = self._log_id_clause(filters.log_ids)
        file_sql, file_params = self._file_like_clause(filters.file_like)
        time_sql, time_params, use_time = self._time_clause(
            filters.time_from, filters.time_to
        )

        sql = f"""
            SELECT {self._victim_select_sql()}
            FROM {self.database}.{self.victim_table}
            WHERE wait_connections != ''
              AND duration >= {{min_duration:UInt64}}
              AND {log_sql}
              AND {host_sql}
              AND {file_sql}
              AND {time_sql}
        """
        params: dict[str, Any] = {
            "min_duration": filters.min_duration_us,
            **host_params,
            **log_params,
            **file_params,
        }
        if filters.process_name:
            sql += " AND lower(process_name) = lower({process_name:String})"
            params["process_name"] = filters.process_name
        sql += " ORDER BY ts ASC"

        if use_time:
            rows = self._query_ts(sql, time_params=time_params, params=params)
        else:
            rows = self._query(sql, params)
        return [_row_to_victim(r, self.victim_event) for r in rows]

    def _find_tx_in_sdbl(
        self,
        connect_id: str,
        reference_ts: datetime,
        log_id: str | None,
        hosts: list[str] | None,
        func: str,
        before: bool,
        offset: int = 0,
    ) -> datetime | None:
        host_sql, host_params = self._host_clause(hosts)
        log_sql, log_params = self._log_id_clause([log_id] if log_id else None)
        if before:
            cmp = "ts < toDateTime64({reference_ts:String}, 6)"
            order = "ORDER BY ts DESC"
        else:
            cmp = "ts > toDateTime64({reference_ts:String}, 6)"
            order = "ORDER BY ts ASC"

        if func == "begin":
            func_filter = "func = {func0:String}"
            func_params = {"func0": "BeginTransaction"}
        else:
            func_filter = (
                "(func IN ({func0:String}, {func1:String}) "
                "OR func LIKE '%CommitTransaction%' "
                "OR func LIKE '%RollbackTransaction%')"
            )
            func_params = {
                "func0": "CommitTransaction",
                "func1": "RollbackTransaction",
            }
        params: dict[str, Any] = {
            "reference_ts": self._ts_literal(reference_ts),
            "connect_id": connect_id,
            **host_params,
            **log_params,
            **func_params,
        }

        sql = f"""
            SELECT ts FROM {self.database}.tj_sdbl
            WHERE connect_id = {{connect_id:String}}
              AND {func_filter}
              AND {cmp}
              AND {host_sql}
              AND {log_sql}
            {order}
            LIMIT 1 OFFSET {offset}
        """
        rows = self._query(sql, params)
        if rows:
            return _parse_ts(rows[0]["ts"])

        if func == "begin":
            raw_func_filter = "extra['func'] = {func0:String}"
        else:
            raw_func_filter = (
                "(extra['func'] IN ({func0:String}, {func1:String}) "
                "OR toString(extra['func']) LIKE '%CommitTransaction%' "
                "OR toString(extra['func']) LIKE '%RollbackTransaction%')"
            )
        sql_raw = f"""
            SELECT ts FROM {self.database}.tj_raw
            WHERE name = 'SDBL'
              AND connect_id = {{connect_id:String}}
              AND {raw_func_filter}
              AND {cmp}
              AND {host_sql}
              AND {log_sql}
            {order}
            LIMIT 1 OFFSET {offset}
        """
        rows = self._query(sql_raw, params)
        if rows:
            return _parse_ts(rows[0]["ts"])
        return None

    def fetch_timeout_wait_tlock(
        self,
        victim: TjEvent,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        timeout_sec: float = 20.0,
        duration_tolerance_sec: float = 2.0,
        ts_window_sec: float = 1.0,
    ) -> TjEvent | None:
        host_sql, host_params = self._host_clause(hosts)
        log_sql, log_params = self._log_id_clause(
            [log_id or victim.log_id] if (log_id or victim.log_id) else None
        )
        min_dur = int(max(0.0, timeout_sec - duration_tolerance_sec) * 1_000_000)
        max_dur = int((timeout_sec + duration_tolerance_sec) * 1_000_000)
        sql = f"""
            SELECT log_id, ts, connect_id, wait_connections, regions, locks, duration,
                   computer_name, process_name, usr, context, escalating, application_name
            FROM {self.database}.tj_tlock
            WHERE connect_id = {{connect_id:String}}
              AND wait_connections = {{wait_connections:String}}
              AND duration >= {{min_duration:UInt64}}
              AND duration <= {{max_duration:UInt64}}
              AND ts >= {{ts_from:DateTime64(6)}}
              AND ts <= {{ts_to:DateTime64(6)}}
              AND {host_sql}
              AND {log_sql}
            ORDER BY abs(duration - {{target_duration:UInt64}}) ASC, ts ASC
            LIMIT 20
        """
        ts_from = victim.ts - timedelta(seconds=ts_window_sec)
        ts_to = victim.ts + timedelta(seconds=ts_window_sec)
        params: dict[str, Any] = {
            "connect_id": victim.connect_id,
            "wait_connections": victim.wait_connections,
            "min_duration": min_dur,
            "max_duration": max_dur,
            "target_duration": int(timeout_sec * 1_000_000),
            **host_params,
            **log_params,
        }
        rows = self._query_ts(
            sql,
            time_params={"ts_from": ts_from, "ts_to": ts_to},
            params=params,
        )
        candidates = [_row_to_victim(r, "TLOCK") for r in rows]
        return pick_timeout_wait_tlock(
            candidates,
            victim,
            timeout_sec=timeout_sec,
            duration_tolerance_sec=duration_tolerance_sec,
            ts_window_sec=ts_window_sec,
        )

    def find_transaction_bounds(
        self,
        connect_id: str,
        reference_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        neighbor_tx: bool = False,
    ) -> TransactionBounds:
        offset = 1 if neighbor_tx else 0
        tx_start = self._find_tx_in_sdbl(
            connect_id, reference_ts, log_id, hosts, "begin", before=True, offset=offset
        )
        if tx_start is None:
            return TransactionBounds(error="Ошибка поиска начала транзакции")

        tx_end = self._find_tx_in_sdbl(
            connect_id, reference_ts, log_id, hosts, "end", before=False, offset=offset
        )
        if tx_end is None:
            tx_end = datetime.now()
        return TransactionBounds(start=tx_start, end=tx_end)

    def _region_clause(self, regions: str) -> tuple[str, dict]:
        spaces = [s.strip().replace("'", "") for s in regions.split(",") if s.strip()]
        if not spaces:
            return "1=1", {}
        parts = []
        params: dict[str, Any] = {}
        for i, sp in enumerate(spaces):
            key = f"region{i}"
            parts.append(f"regions LIKE {{{key}:String}}")
            params[key] = f"%{sp}%"
        if len(parts) == 1:
            return parts[0], params
        return "(" + " OR ".join(parts) + ")", params

    def fetch_culprit_tlocks(
        self,
        connect_id: str,
        tx_start: datetime,
        tx_end: datetime,
        region_filter: str,
        victim_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
        limit: int = 2001,
    ) -> list[TjEvent]:
        host_sql, host_params = self._host_clause(hosts)
        log_sql, log_params = self._log_id_clause([log_id] if log_id else None)
        region_sql, region_params = (
            self._region_clause(region_filter)
            if region_filter.strip()
            else ("1=1", {})
        )
        sql = f"""
            SELECT log_id, ts, connect_id, wait_connections, regions, locks, duration,
                   computer_name, process_name, usr, context, escalating, application_name
            FROM {self.database}.tj_tlock
            WHERE connect_id = {{connect_id:String}}
              AND ts >= {{tx_start:DateTime64(6)}}
              AND ts <= {{tx_end:DateTime64(6)}}
              AND {region_sql}
              AND {host_sql}
              AND {log_sql}
            ORDER BY ts ASC
            LIMIT {{limit:UInt32}}
        """
        params: dict[str, Any] = {
            "connect_id": connect_id,
            "limit": limit,
            **host_params,
            **log_params,
            **region_params,
        }
        rows = self._query_ts(
            sql,
            time_params={"tx_start": tx_start, "tx_end": tx_end},
            params=params,
        )
        return [_row_to_victim(r, "TLOCK") for r in rows]

    def fetch_context(
        self,
        connect_id: str,
        before_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
    ) -> str:
        host_sql, host_params = self._host_clause(hosts)
        log_sql, log_params = self._log_id_clause([log_id] if log_id else None)
        sql = f"""
            SELECT context FROM {self.database}.tj_raw
            WHERE name = 'Context'
              AND connect_id = {{connect_id:String}}
              AND ts < toDateTime64({{before_ts:String}}, 6)
              AND {host_sql}
              AND {log_sql}
            ORDER BY ts ASC
            LIMIT 1
        """
        params = {
            "connect_id": connect_id,
            "before_ts": self._ts_literal(before_ts),
            **host_params,
            **log_params,
        }
        rows = self._query(sql, params)
        if rows and rows[0].get("context"):
            return str(rows[0]["context"])
        return ""

    def fetch_transaction_context(
        self,
        connect_id: str,
        at_ts: datetime,
        log_id: str | None = None,
        hosts: list[str] | None = None,
    ) -> str:
        host_sql, host_params = self._host_clause(hosts)
        log_sql, log_params = self._log_id_clause([log_id] if log_id else None)
        sql = f"""
            SELECT context FROM {self.database}.tj_sdbl
            WHERE connect_id = {{connect_id:String}}
              AND ts = toDateTime64({{at_ts:String}}, 6)
              AND {host_sql}
              AND {log_sql}
            LIMIT 1
        """
        params = {
            "connect_id": connect_id,
            "at_ts": self._ts_literal(at_ts),
            **host_params,
            **log_params,
        }
        rows = self._query(sql, params)
        if rows and rows[0].get("context"):
            return str(rows[0]["context"])
        return self.fetch_context(connect_id, at_ts, log_id=log_id, hosts=hosts)

    def clone(self) -> ClickHouseSource:
        """Independent connection for parallel agent workers."""
        return ClickHouseSource(
            host=self._connect_host,
            port=self._connect_port,
            username=self._connect_username,
            password=self._connect_password,
            database=self.database,
            secure=self._connect_secure,
            victim_table=self.victim_table,
            victim_event=self.victim_event,
        )
