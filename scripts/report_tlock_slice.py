"""Generate markdown report for a TLOCK file slice in ClickHouse."""

from __future__ import annotations

import argparse
import os

from clickhouse_connect import get_client

from tj_common.analysis.pipeline import run_analysis
from tj_common.models import QueryFilters
from tj_common.report.labels import TLOCK_LABELS
from tj_common.report.markdown import render_event_markdown
from tj_common.sources.clickhouse import ClickHouseSource
from tj_common.utils import apply_mcp_clickhouse_env, clickhouse_config_from_env

LOG_ID = "teletrade20260604__tr20260604"
FILE_PATTERN = "%tlock_1607235%"
OUTPUT = "reports/tlock_1607235_teletrade20260604.md"
OUTPUT_VICTIMS = "reports/tlock_1607235_victims_full.md"


def build_victim_analysis_markdown(time_from, time_to) -> tuple[str, int]:
    """Run tlock_analyzer for all victims in log_id within slice time window."""
    cfg = clickhouse_config_from_env()
    ch = ClickHouseSource(
        host=cfg["host"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        database=cfg["database"],
        secure=cfg["secure"],
    )
    filters = QueryFilters(
        log_ids=[LOG_ID],
        time_from=time_from,
        time_to=time_to,
        min_duration_us=0,
    )
    result = run_analysis(ch, filters)
    header = [
        "# Анализ ожиданий TLOCK (жертва / виновник)",
        "",
        f"**log_id:** `{LOG_ID}`  ",
        f"**Период (как у среза `tlock_1607235`):** {time_from} — {time_to}",
        "",
        f"**Жертв (ожиданий):** {len(result.victims)}  ",
        f"**Ошибок обработки:** {len(result.errors)}",
        "",
        "---",
        "",
    ]
    body = render_event_markdown(result, TLOCK_LABELS)
    if body.startswith("# "):
        body = body.split("\n", 1)[1].lstrip("\n")
    return "\n".join(header) + body, len(result.victims)


def build_summary_lines(c, time_from, time_to, victim_count: int) -> list[str]:
    p = {"lid": LOG_ID, "pat": FILE_PATTERN}

    def q(sql: str, **extra):
        return c.query(sql, parameters={**p, **extra}).result_rows

    summary = q(
        """
        SELECT count(), countIf(wait_connections != ''), min(ts), max(ts),
          uniqExact(connect_id), uniqExact(regions)
        FROM tj_tlock WHERE log_id=%(lid)s AND file LIKE %(pat)s
        """
    )[0]
    files = q(
        """
        SELECT extractAllGroups(file, 'rphost_(\\d+)')[1][1], computer_name, count()
        FROM tj_tlock WHERE log_id=%(lid)s AND file LIKE %(pat)s
        GROUP BY 1, 2 ORDER BY count() DESC LIMIT 12
        """
    )
    regions = q(
        """
        SELECT regions, count(), round(max(duration)/1e6, 4)
        FROM tj_tlock WHERE log_id=%(lid)s AND file LIKE %(pat)s
        GROUP BY regions ORDER BY count() DESC
        """
    )
    hourly = q(
        """
        SELECT toStartOfHour(ts), count(),
          countIf(regions LIKE 'InfoRg17707%%'),
          countIf(regions LIKE 'AccumRg10479%%')
        FROM tj_tlock WHERE log_id=%(lid)s AND file LIKE %(pat)s
        GROUP BY 1 ORDER BY 1
        """
    )
    holders = q(
        """
        SELECT connect_id, count(), round(avg(duration)/1e6, 4)
        FROM tj_tlock WHERE log_id=%(lid)s AND file LIKE %(pat)s
        GROUP BY connect_id ORDER BY count() DESC LIMIT 12
        """
    )
    modes = q(
        """
        SELECT
          if(position(locks,'Exclusive')>0,'Exclusive',
             if(position(locks,'Shared')>0,'Shared','Other')), count()
        FROM tj_tlock WHERE log_id=%(lid)s AND file LIKE %(pat)s
          AND regions='InfoRg17707.DIMS'
        GROUP BY 1
        """
    )
    cross = q(
        """
        SELECT v.ts, v.connect_id, v.wait_connections,
               round(v.duration/1e6, 3), v.regions
        FROM tj_tlock v
        WHERE v.log_id=%(lid)s AND v.wait_connections != ''
          AND v.wait_connections IN (
            SELECT DISTINCT connect_id FROM tj_tlock
            WHERE log_id=%(lid)s AND file LIKE %(pat)s
          )
        ORDER BY v.duration DESC
        """
    )

    lines: list[str] = [
        "# Отчёт: TLOCK `tlock_1607235`",
        "",
        "```sql",
        "SELECT * FROM onec_logs.tj_tlock",
        f"WHERE log_id = '{LOG_ID}'",
        "  AND file LIKE '%tlock_1607235%'",
        "```",
        "",
        "## Сводка",
        "",
        "| Метрика | Значение |",
        "|---------|----------|",
        f"| Событий TLOCK в файлах среза | **{summary[0]}** |",
        f"| Ожидания в файлах tlock_1607235 | **{summary[1]}** |",
        f"| Период среза | {summary[2]} — {summary[3]} |",
        f"| Ожиданий за период (все файлы log_id) | **{victim_count}** |",
        f"| Уникальных connect_id в срезе | {summary[4]} |",
        "",
        "> В **файлах** `tlock_1607235` только захваты блокировок. "
        f"Разбор **{victim_count}** ожиданий за тот же период: "
        f"[`tlock_1607235_victims_full.md`](tlock_1607235_victims_full.md).",
        "",
        "## Файлы и хосты",
        "",
        "| rphost | computer_name | TLOCK |",
        "|--------|---------------|------:|",
    ]
    for rp, hn, cnt in files:
        lines.append(f"| {rp} | {hn} | {cnt} |")

    lines += [
        "",
        "## Регистры (в срезе файла)",
        "",
        "| regions | TLOCK | max duration (сек) |",
        "|---------|------:|-------------------:|",
    ]
    for rg, cnt, mx in regions:
        lines.append(f"| {rg} | {cnt} | {mx} |")

    lines += [
        "",
        "### InfoRg17707.DIMS — режим",
        "",
        "| Режим | Количество |",
        "|-------|----------:|",
    ]
    for m, cnt in modes:
        lines.append(f"| {m} | {cnt} |")

    lines += [
        "",
        "## Нагрузка по часам (срез файла)",
        "",
        "| Час | TLOCK | InfoRg17707 | AccumRg10479 |",
        "|-----|------:|------------:|-------------:|",
    ]
    for h, cnt, i7, a4 in hourly:
        if cnt:
            lines.append(f"| {h} | {cnt} | {i7} | {a4} |")

    lines += [
        "",
        "## Топ connect_id (срез файла)",
        "",
        "| connect_id | TLOCK | ср. duration (сек) |",
        "|------------|------:|-------------------:|",
    ]
    for cid, cnt, av in holders:
        lines.append(f"| {cid} | {cnt} | {av} |")

    lines += [
        "",
        "## Ожидания на держателей из среза (другие файлы ТЖ)",
        "",
    ]
    if cross:
        lines += [
            "| Время | Жертва | Виновник | Длит. (сек) | Регион |",
            "|-------|--------|----------|------------:|--------|",
        ]
        for row in cross:
            lines.append(
                f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |"
            )
    else:
        lines.append("*(нет)*")

    lines += [
        "",
        "## Выводы",
        "",
        "1. SQL по `file` — только захваты; `tlock_analyzer` работает по ожиданиям за **период** среза.",
        "2. Доминирует **666627** / **InfoRg17707** на **vTerm07**.",
        "3. Полный отчёт по каждой жертве — **`tlock_1607235_victims_full.md`**.",
        "",
    ]
    return lines


def slice_time_bounds(c) -> tuple[object, object]:
    row = c.query(
        """
        SELECT min(ts), max(ts) FROM tj_tlock
        WHERE log_id=%(lid)s AND file LIKE %(pat)s
        """,
        parameters={"lid": LOG_ID, "pat": FILE_PATTERN},
    ).result_rows[0]
    return row[0], row[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Report for TLOCK file slice in CH")
    parser.add_argument("--victims-only", action="store_true")
    parser.add_argument("--no-victims", action="store_true")
    args = parser.parse_args()

    apply_mcp_clickhouse_env()
    cfg = clickhouse_config_from_env()
    c = get_client(
        host=cfg["host"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        database=cfg["database"],
        secure=cfg["secure"],
    )
    os.makedirs("reports", exist_ok=True)

    t_from, t_to = slice_time_bounds(c)

    victim_count = c.query(
        """
        SELECT count() FROM tj_tlock
        WHERE log_id=%(lid)s AND wait_connections != ''
          AND ts >= %(t_from)s AND ts <= %(t_to)s
        """,
        parameters={
            "lid": LOG_ID,
            "t_from": t_from,
            "t_to": t_to,
        },
    ).result_rows[0][0]

    if not args.victims_only:
        lines = build_summary_lines(c, t_from, t_to, victim_count)
        with open(OUTPUT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(OUTPUT)

    if not args.no_victims:
        victim_md, n = build_victim_analysis_markdown(t_from, t_to)
        with open(OUTPUT_VICTIMS, "w", encoding="utf-8") as f:
            f.write(victim_md)
        print(f"{OUTPUT_VICTIMS} ({n} victims)")


if __name__ == "__main__":
    main()
