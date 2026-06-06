"""Per-event victim/culprit report blocks (text and markdown)."""

from __future__ import annotations

from tj_common.models import (
    AnalysisResult,
    CulpritAnalysis,
    CulpritTlockRow,
    VictimAnalysis,
)
from tj_common.report.labels import ReportLabels
from tj_common.utils import format_ts

CONFLICT_LABELS = {
    "full_match": "Полное соответствие",
    "escalation": "Эскалация",
    "different_dimensions": "Разный набор измерений",
}


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def normalize_context(text: str) -> str:
    """Remove empty lines from tech journal context."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line for line in lines if line.strip())


def _md_code_block(text: str) -> list[str]:
    body = normalize_context(text)
    if not body:
        return ["", "*(пусто)*", ""]
    return ["", "```", body, "```", ""]


def _tx_duration_sec(c: CulpritAnalysis) -> float | None:
    if c.tx_duration_us is not None:
        return c.tx_duration_us / 1_000_000
    if c.tx_start and c.tx_end:
        return (c.tx_end - c.tx_start).total_seconds()
    return None


def _conflict_tlock_rows(c: CulpritAnalysis) -> list[CulpritTlockRow]:
    if c.tx_tlocks_conflict:
        return c.tx_tlocks_conflict
    rows: list[CulpritTlockRow] = []
    for key, label in CONFLICT_LABELS.items():
        for d in getattr(c, key, []) or []:
            rows.append(
                CulpritTlockRow(
                    timestamp=_parse_ts_from_dict(d),
                    duration_sec=float(d.get("Duration", 0) or 0) / 1_000_000,
                    regions=str(d.get("Regions", "")),
                    locks=str(d.get("Locks", "")),
                    context=str(d.get("Context", "")),
                    conflict_type=label,
                )
            )
    return rows


def _parse_ts_from_dict(d: dict) -> object:
    from datetime import datetime

    ts = d.get("Timestamp", "")
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.now()


def _format_tlock_context_sections(rows: list[CulpritTlockRow]) -> list[str]:
    """Context blocks for culprit TLOCK rows (BSL: Контекст per intersection TLOCK)."""
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
        lines.append(f"**Контекст TLOCK** `{format_ts(row.timestamp)}`")
        lines.extend(_md_code_block(body))
    return lines


def _victim_table_rows(victim: VictimAnalysis) -> list[list[str]]:
    ev = victim.event
    return [
        [
            ev.connect_id,
            format_ts(ev.ts),
            f"{ev.duration_sec:.6f}",
            ev.wait_connections,
            ev.regions,
            ev.locks,
        ]
    ]


def _format_culprit_markdown(c: CulpritAnalysis) -> list[str]:
    lines: list[str] = []
    lines.append(f"### Виновник `connect_id={c.connect_id}`")
    lines.append("")

    if c.error:
        lines.append(f"**Ошибка:** {c.error}")
        lines.append("")
        return lines

    start = c.tx_start_boundary
    if start and start.timestamp:
        lines.append("#### Начало транзакции")
        lines.extend(
            _md_table(["Время"], [[format_ts(start.timestamp)]])
        )
        lines.append("")
    elif c.tx_start:
        lines.append(f"#### Начало транзакции: {format_ts(c.tx_start)}")
        lines.append("")

    conflict_rows = _conflict_tlock_rows(c)
    if conflict_rows:
        lines.append("#### TLOCK с пересечением")
        lines.append("")
        tlock_table = [
            [
                format_ts(r.timestamp),
                f"{r.duration_sec:.6f}",
                r.conflict_type or "",
                r.regions,
                r.locks,
            ]
            for r in conflict_rows
        ]
        lines.extend(
            _md_table(
                ["Время", "Длительность (сек)", "Тип", "Пространство", "Ресурсы"],
                tlock_table,
            )
        )
        lines.append("")
        lines.extend(_format_tlock_context_sections(conflict_rows))
    elif c.big_transaction:
        lines.append(
            f"#### TLOCK с пересечением\n\n"
            f"*(большая транзакция: >2000 событий в фильтре региона, "
            f"уникальных контекстов: {len(c.big_transaction)})*"
        )
        lines.append("")
    else:
        lines.append("#### TLOCK с пересечением")
        lines.append("")
        lines.append("*(пересечений нет — все TLOCK в периоде транзакции)*")
        lines.append("")
        lines.append("#### Все TLOCK в транзакции")
        lines.append("")
        if c.tx_tlocks_all:
            lines.extend(
                _md_table(
                    ["Время", "Длительность (сек)", "Пространство", "Ресурсы"],
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
            lines.extend(_format_tlock_context_sections(c.tx_tlocks_all))
        else:
            lines.append("*(нет TLOCK в транзакции)*")
            lines.append("")

    end = c.tx_end_boundary
    dur = _tx_duration_sec(c)
    dur_s = f"{dur:.6f}" if dur is not None else "—"
    lines.append("#### Конец транзакции")
    if end and end.timestamp:
        lines.extend(
            _md_table(
                ["Время", "Длительность транзакции (сек)"],
                [[format_ts(end.timestamp), dur_s]],
            )
        )
    elif c.tx_end:
        lines.extend(
            _md_table(
                ["Время", "Длительность транзакции (сек)"],
                [[format_ts(c.tx_end), dur_s]],
            )
        )
    lines.append("")
    return lines


def render_event_markdown(
    result: AnalysisResult, labels: ReportLabels
) -> str:
    parts: list[str] = []
    parts.append(f"# {labels.title}")
    parts.append("")

    for idx, victim in enumerate(result.victims, 1):
        parts.append(f"## Событие #{idx}")
        parts.append("")
        parts.append("### Жертва")
        parts.append("")
        parts.extend(
            _md_table(
                [
                    "Соединение",
                    "Время",
                    "Длительность (сек)",
                    "Виновник (соединение)",
                    "Регион",
                    "Locks",
                ],
                _victim_table_rows(victim),
            )
        )
        parts.append("")
        parts.append("**Контекст**")
        parts.extend(_md_code_block(victim.event.context))

        if victim.parse_error:
            parts.append(f"**Ошибка:** {victim.parse_error}")
            parts.append("")
            continue

        for c in victim.culprits:
            parts.extend(_format_culprit_markdown(c))

    if result.errors:
        parts.append("## Ошибки обработки")
        parts.append("")
        for err in result.errors:
            parts.append(f"- {err}")
        parts.append("")

    return "\n".join(parts)
