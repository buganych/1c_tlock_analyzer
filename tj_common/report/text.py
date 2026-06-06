"""Human-readable report — same structure as markdown, plain text."""

from __future__ import annotations

from tj_common.models import AnalysisResult, CulpritAnalysis, CulpritTlockRow
from tj_common.report.event_report import (
    _conflict_tlock_rows,
    _tx_duration_sec,
    _victim_table_rows,
    normalize_context,
)
from tj_common.report.labels import ReportLabels, TLOCK_LABELS
from tj_common.utils import format_ts


def _plain_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    sep = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    lines = [sep, "-+-".join("-" * w for w in widths)]
    for row in rows:
        lines.append(" | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
    return lines


def _plain_tlock_context_sections(rows: list[CulpritTlockRow]) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        body = normalize_context(row.context)
        if not body:
            continue
        key = (format_ts(row.timestamp), body)
        if key in seen:
            continue
        seen.add(key)
        lines.extend(_plain_context(f"Контекст TLOCK {format_ts(row.timestamp)}", body))
    return lines


def _plain_context(title: str, text: str) -> list[str]:
    lines = [title, "-" * len(title)]
    body = normalize_context(text)
    if body:
        lines.append(body)
    else:
        lines.append("(пусто)")
    lines.append("")
    return lines


def _format_culprit_text(c: CulpritAnalysis) -> list[str]:
    lines: list[str] = []
    lines.append(f"  Виновник connect_id={c.connect_id}")
    lines.append("")

    if c.error:
        lines.append(f"  Ошибка: {c.error}")
        lines.append("")
        return lines

    start = c.tx_start_boundary
    lines.append("  Начало транзакции")
    if start and start.timestamp:
        lines.extend(_plain_table(["Время"], [[format_ts(start.timestamp)]]))
        lines.append("")
    elif c.tx_start:
        lines.append(f"    Время: {format_ts(c.tx_start)}")
        lines.append("")

    conflict_rows = _conflict_tlock_rows(c)
    if conflict_rows:
        lines.append("  TLOCK с пересечением")
        lines.extend(
            _plain_table(
                ["Время", "Длительность", "Тип", "Пространство", "Ресурсы"],
                [
                    [
                        format_ts(r.timestamp),
                        f"{r.duration_sec:.6f}",
                        r.conflict_type,
                        r.regions,
                        r.locks,
                    ]
                    for r in conflict_rows
                ],
            )
        )
        lines.append("")
        lines.extend(_plain_tlock_context_sections(conflict_rows))
    elif c.big_transaction:
        lines.append(
            f"  TLOCK с пересечением: большая транзакция "
            f"({len(c.big_transaction)} уник. контекстов)"
        )
        lines.append("")
    else:
        lines.append("  TLOCK с пересечением: (нет)")
        lines.append("  Все TLOCK в транзакции")
        if c.tx_tlocks_all:
            lines.extend(
                _plain_table(
                    ["Время", "Длительность", "Пространство", "Ресурсы"],
                    [
                        [
                            format_ts(r.timestamp),
                            f"{r.duration_sec:.6f}",
                            r.regions,
                            r.locks,
                        ]
                        for r in c.tx_tlocks_all
                    ],
                )
            )
            lines.append("")
            lines.extend(_plain_tlock_context_sections(c.tx_tlocks_all))
        else:
            lines.append("    (нет TLOCK в транзакции)")
            lines.append("")

    end = c.tx_end_boundary
    dur = _tx_duration_sec(c)
    dur_s = f"{dur:.6f}" if dur is not None else "—"
    lines.append("  Конец транзакции")
    if end and end.timestamp:
        lines.extend(
            _plain_table(
                ["Время", "Длительность транзакции (сек)"],
                [[format_ts(end.timestamp), dur_s]],
            )
        )
    elif c.tx_end:
        lines.append(f"    Время: {format_ts(c.tx_end)}, длительность: {dur_s} сек.")
        lines.append("")
    return lines


def render_text(
    result: AnalysisResult, labels: ReportLabels = TLOCK_LABELS
) -> str:
    parts: list[str] = []
    parts.append("=" * 60)
    parts.append(labels.title)
    parts.append("=" * 60)

    for idx, victim in enumerate(result.victims, 1):
        parts.append("")
        parts.append(f"--- Событие #{idx} ---")
        parts.append("")
        parts.append("Жертва")
        parts.extend(
            _plain_table(
                [
                    "Соединение",
                    "Время",
                    "Длительность",
                    "Виновник",
                    "Регион",
                    "Locks",
                ],
                _victim_table_rows(victim),
            )
        )
        parts.append("")
        parts.extend(_plain_context("Контекст жертвы", victim.event.context))

        if victim.parse_error:
            parts.append(f"Ошибка: {victim.parse_error}")
            continue

        for c in victim.culprits:
            parts.extend(_format_culprit_text(c))

    if result.errors:
        parts.append("")
        parts.append("--- Ошибки обработки ---")
        parts.extend(result.errors)

    return "\n".join(parts)
