"""Shared table rendering for CALL reports."""

from __future__ import annotations

import html

from tj_common.models_call import CallTopRow, VISIBLE_ROWS_DEFAULT


def split_rows(
    rows: list[CallTopRow], visible_n: int = VISIBLE_ROWS_DEFAULT
) -> tuple[list[CallTopRow], list[CallTopRow]]:
    n = max(1, visible_n)
    return rows[:n], rows[n:]


def md_metric_table(rows: list[CallTopRow], unit: str) -> list[str]:
    lines = [
        f"| Контекст | Средняя ({unit}) | Максимальная ({unit}) | Минимальная ({unit}) | "
        f"Всего ({unit}) | Кол-во |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.context} | {row.avg} | {row.max} | {row.min} | {row.total} | {row.count} |"
        )
    return lines


def md_table_section(
    rows: list[CallTopRow],
    unit: str,
    *,
    visible_n: int = VISIBLE_ROWS_DEFAULT,
) -> list[str]:
    if not rows:
        return ["*(нет данных)*", ""]
    visible, hidden = split_rows(rows, visible_n)
    lines = md_metric_table(visible, unit)
    if hidden:
        lines.append("")
        lines.append("<details>")
        lines.append(f"<summary>Ещё {len(hidden)}</summary>")
        lines.append("")
        lines.extend(md_metric_table(hidden, unit))
        lines.append("</details>")
    lines.append("")
    return lines


def html_metric_table(rows: list[CallTopRow], unit: str) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(row.context)}</td>"
            f'<td class="num">{row.avg}</td>'
            f'<td class="num">{row.max}</td>'
            f'<td class="num">{row.min}</td>'
            f'<td class="num">{row.total}</td>'
            f'<td class="num">{row.count}</td>'
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr>"
        f"<th>Контекст</th><th>Средняя ({html.escape(unit)})</th>"
        f"<th>Максимальная ({html.escape(unit)})</th>"
        f"<th>Минимальная ({html.escape(unit)})</th>"
        f"<th>Всего ({html.escape(unit)})</th>"
        "<th>Кол-во</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def html_table_section(
    rows: list[CallTopRow],
    unit: str,
    *,
    visible_n: int = VISIBLE_ROWS_DEFAULT,
) -> str:
    if not rows:
        return "<p><em>нет данных</em></p>"
    visible, hidden = split_rows(rows, visible_n)
    parts = [html_metric_table(visible, unit)]
    if hidden:
        parts.append(
            '<details class="summary-more">'
            f"<summary>Ещё {len(hidden)}</summary>"
            f"{html_metric_table(hidden, unit)}"
            "</details>"
        )
    return "".join(parts)
