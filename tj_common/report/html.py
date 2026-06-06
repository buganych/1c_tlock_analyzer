"""HTML report with table of contents and anchor links."""

from __future__ import annotations

import html
import re
from typing import Any

from tj_common.analysis.unified_pipeline import UnifiedAnalysisResult
from tj_common.models import AnalysisResult, CulpritAnalysis, CulpritTlockRow, VictimAnalysis
from tj_common.models_deadlock import DeadlockAnalysisResult, TimelineEvent
from tj_common.report.event_report import (
    _conflict_tlock_rows,
    _tx_duration_sec,
    _victim_table_rows,
    normalize_context,
)
from tj_common.report.labels import ReportLabels, TLOCK_LABELS, TTIMEOUT_LABELS
from tj_common.utils import format_ts

_HTML_STYLES = """
:root {
  --bg: #f6f8fa;
  --card: #ffffff;
  --text: #1f2328;
  --muted: #656d76;
  --border: #d0d7de;
  --accent: #0969da;
  --code-bg: #eff1f3;
  --toc-bg: #f0f4f8;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  color: var(--text);
  background: var(--bg);
}
.layout {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 20px 48px;
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 24px;
  align-items: start;
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  nav.toc { position: static; }
}
nav.toc {
  position: sticky;
  top: 16px;
  background: var(--toc-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
nav.toc h2 {
  margin: 0 0 12px;
  font-size: 15px;
}
nav.toc ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
nav.toc li { margin: 4px 0; }
nav.toc a {
  color: var(--accent);
  text-decoration: none;
}
nav.toc a:hover { text-decoration: underline; }
nav.toc .lvl-1 { font-weight: 600; margin-top: 8px; }
nav.toc .lvl-2 { padding-left: 12px; }
nav.toc .lvl-3 { padding-left: 24px; font-size: 13px; }
main.content {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px 28px;
}
h1 { font-size: 22px; margin: 0 0 16px; }
h2 { font-size: 18px; margin: 28px 0 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
h3 { font-size: 16px; margin: 20px 0 10px; }
h4 { font-size: 14px; margin: 16px 0 8px; color: var(--muted); }
p.meta { color: var(--muted); margin: 0 0 12px; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0 16px;
  font-size: 13px;
}
th, td {
  border: 1px solid var(--border);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
th { background: #f6f8fa; }
pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.context-label { font-weight: 600; margin: 12px 0 4px; }
.muted { color: var(--muted); font-style: italic; }
.summary-table { max-width: 420px; }
hr.section { border: none; border-top: 2px solid var(--border); margin: 32px 0; }
table.tlock-table tr.tlock-data td { border-bottom: none; }
table.tlock-table tr.tlock-context td {
  padding: 0 8px 8px;
  border-top: none;
  background: #fafbfc;
}
table.tlock-table details { margin: 0; }
table.tlock-table summary {
  cursor: pointer;
  color: var(--accent);
  font-size: 12px;
  padding: 4px 0;
  user-select: none;
}
table.tlock-table summary:hover { text-decoration: underline; }
table.tlock-table details pre {
  margin: 6px 0 0;
  font-size: 12px;
}
table.timeline-table tr.timeline-data td { border-bottom: none; }
table.timeline-table tr.timeline-extra td,
table.timeline-table tr.timeline-context td {
  padding: 0 8px 8px;
  border-top: none;
  background: #fafbfc;
}
table.timeline-table tr.timeline-extra td {
  font-size: 12px;
  color: var(--muted);
  padding-top: 2px;
}
table.timeline-table details { margin: 0; }
table.timeline-table summary {
  cursor: pointer;
  color: var(--accent);
  font-size: 12px;
  padding: 4px 0;
  user-select: none;
}
table.timeline-table summary:hover { text-decoration: underline; }
table.timeline-table details pre {
  margin: 6px 0 0;
  font-size: 12px;
}
"""


def _normalize_timeline_time(time_str: str) -> str:
    return time_str.replace("T", " ", 1) if "T" in time_str else time_str


def _timeline_event_label(ev: TimelineEvent) -> str:
    if ev.wait:
        return "Ожидание" if ev.is_wait else "Блокировка"
    return ev.label


def _context_details_html(context: str) -> str:
    body = normalize_context(context)
    if body:
        return (
            f"<details><summary>Контекст</summary>"
            f"<pre><code>{html.escape(body)}</code></pre></details>"
        )
    return '<span class="muted">(пусто)</span>'


def _slug(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[`*]", "", s)
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s, flags=re.UNICODE)
    return s.strip("-") or "section"


class _HtmlBuilder:
    def __init__(self) -> None:
        self._toc: list[tuple[int, str, str]] = []
        self._chunks: list[str] = []
        self._ids: dict[str, int] = {}

    def _unique_id(self, text: str) -> str:
        base = _slug(text)
        count = self._ids.get(base, 0)
        self._ids[base] = count + 1
        return base if count == 0 else f"{base}-{count + 1}"

    def heading(self, level: int, text: str, *, toc: bool = True, toc_level: int | None = None) -> str:
        hid = self._unique_id(text)
        if toc:
            self._toc.append((toc_level or level, hid, text))
        self._chunks.append(f"<h{level} id=\"{hid}\">{html.escape(text)}</h{level}>")
        return hid

    def raw(self, fragment: str) -> None:
        self._chunks.append(fragment)

    def paragraph(self, text: str, *, css_class: str = "") -> None:
        cls = f' class="{css_class}"' if css_class else ""
        self._chunks.append(f"<p{cls}>{html.escape(text)}</p>")

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body_rows = []
        for row in rows:
            cells = "".join(f"<td>{html.escape(str(c))}</td>" for c in row)
            body_rows.append(f"<tr>{cells}</tr>")
        self._chunks.append(
            "<table><thead><tr>"
            + head
            + "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table>"
        )

    def tlock_table(self, headers: list[str], rows: list[tuple[list[str], str]]) -> None:
        """Culprit TLOCK table: data row + expandable context row underneath."""
        col_count = len(headers)
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body_rows: list[str] = []
        for cells, context in rows:
            data_cells = "".join(f"<td>{html.escape(str(c))}</td>" for c in cells)
            body_rows.append(f'<tr class="tlock-data">{data_cells}</tr>')
            body_rows.append(
                f'<tr class="tlock-context"><td colspan="{col_count}">'
                f"{_context_details_html(context)}</td></tr>"
            )
        self._chunks.append(
            '<table class="tlock-table"><thead><tr>'
            + head
            + "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table>"
        )

    def code_block(self, text: str) -> None:
        body = normalize_context(text)
        if not body:
            self.raw('<p class="muted">(пусто)</p>')
            return
        self._chunks.append(f"<pre><code>{html.escape(body)}</code></pre>")

    def context_section(self, title: str, text: str) -> None:
        self.raw(f'<p class="context-label">{html.escape(title)}</p>')
        self.code_block(text)

    def deadlock_timeline_table(self, events: list[TimelineEvent]) -> None:
        headers = ["Время", "Участник", "Событие"]
        col_count = len(headers)
        head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        body_rows: list[str] = []
        for ev in events:
            cells = "".join(
                f"<td>{html.escape(str(c))}</td>"
                for c in (
                    _normalize_timeline_time(ev.time),
                    ev.role,
                    _timeline_event_label(ev),
                )
            )
            body_rows.append(f'<tr class="timeline-data">{cells}</tr>')
            if ev.wait:
                space = f"{ev.wait.regions} {ev.wait.level}".strip()
                body_rows.append(
                    f'<tr class="timeline-extra"><td colspan="{col_count}">'
                    f"Пространство: {html.escape(space)}</td></tr>"
                )
                body_rows.append(
                    f'<tr class="timeline-context"><td colspan="{col_count}">'
                    f"{_context_details_html(ev.wait.context or '')}</td></tr>"
                )
        self._chunks.append(
            '<table class="timeline-table"><thead><tr>'
            + head
            + "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table>"
        )

    def tlock_context_sections(self, rows: list[CulpritTlockRow]) -> None:
        seen: set[tuple[str, str]] = set()
        for row in rows:
            body = normalize_context(row.context)
            if not body:
                continue
            key = (format_ts(row.timestamp), body)
            if key in seen:
                continue
            seen.add(key)
            self.context_section(f"Контекст TLOCK {format_ts(row.timestamp)}", body)

    def render_document(self, title: str, meta: str = "") -> str:
        toc_items = []
        for lvl, hid, label in self._toc:
            toc_items.append(
                f'<li class="lvl-{lvl}"><a href="#{hid}">{html.escape(label)}</a></li>'
            )
        meta_html = f'<p class="meta">{html.escape(meta)}</p>' if meta else ""
        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_HTML_STYLES}</style>
</head>
<body>
  <div class="layout">
    <nav class="toc">
      <h2>Оглавление</h2>
      <ul>
        {''.join(toc_items)}
      </ul>
    </nav>
    <main class="content">
      <h1>{html.escape(title)}</h1>
      {meta_html}
      {''.join(self._chunks)}
    </main>
  </div>
</body>
</html>"""


def _format_culprit_html(b: _HtmlBuilder, c: CulpritAnalysis) -> None:
    b.heading(3, f"Виновник connect_id={c.connect_id}", toc_level=3)
    if c.error:
        b.paragraph(f"Ошибка: {c.error}")
        return

    start = c.tx_start_boundary
    b.heading(4, "Начало транзакции", toc=False)
    if start and start.timestamp:
        b.table(["Время"], [[format_ts(start.timestamp)]])
    elif c.tx_start:
        b.paragraph(format_ts(c.tx_start))

    conflict_rows = _conflict_tlock_rows(c)
    b.heading(4, "TLOCK с пересечением", toc=False)
    if conflict_rows:
        b.tlock_table(
            ["Время", "Длительность (сек)", "Тип", "Пространство", "Ресурсы"],
            [
                (
                    [
                        format_ts(r.timestamp),
                        f"{r.duration_sec:.6f}",
                        r.conflict_type or "",
                        r.regions,
                        r.locks,
                    ],
                    r.context,
                )
                for r in conflict_rows
            ],
        )
    elif c.big_transaction:
        b.paragraph(
            f"Большая транзакция: >2000 событий, уникальных контекстов: {len(c.big_transaction)}",
            css_class="muted",
        )
    else:
        b.paragraph("Пересечений нет — все TLOCK в периоде транзакции", css_class="muted")
        b.heading(4, "Все TLOCK в транзакции", toc=False)
        if c.tx_tlocks_all:
            b.tlock_table(
                ["Время", "Длительность (сек)", "Пространство", "Ресурсы"],
                [
                    (
                        [
                            format_ts(r.timestamp),
                            f"{r.duration_sec:.6f}",
                            r.regions,
                            r.locks,
                        ],
                        r.context,
                    )
                    for r in c.tx_tlocks_all
                ],
            )
        else:
            b.paragraph("Нет TLOCK в транзакции", css_class="muted")

    end = c.tx_end_boundary
    dur = _tx_duration_sec(c)
    dur_s = f"{dur:.6f}" if dur is not None else "—"
    b.heading(4, "Конец транзакции", toc=False)
    if end and end.timestamp:
        b.table(
            ["Время", "Длительность транзакции (сек)"],
            [[format_ts(end.timestamp), dur_s]],
        )
    elif c.tx_end:
        b.table(
            ["Время", "Длительность транзакции (сек)"],
            [[format_ts(c.tx_end), dur_s]],
        )


def _render_victim_html(b: _HtmlBuilder, victim: VictimAnalysis, idx: int) -> None:
    b.heading(2, f"Событие #{idx}", toc_level=2)
    b.heading(3, "Жертва", toc=False)
    b.table(
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
    b.context_section("Контекст", victim.event.context)
    if victim.parse_error:
        b.paragraph(f"Ошибка: {victim.parse_error}")
        return
    for c in victim.culprits:
        _format_culprit_html(b, c)


def render_event_html(
    result: AnalysisResult,
    labels: ReportLabels = TLOCK_LABELS,
    *,
    doc_title: str | None = None,
    meta: str = "",
) -> str:
    b = _HtmlBuilder()
    section_title = labels.title
    b.heading(2, section_title, toc_level=1)
    for idx, victim in enumerate(result.victims, 1):
        _render_victim_html(b, victim, idx)
    if result.errors:
        b.heading(2, "Ошибки обработки", toc_level=1)
        for err in result.errors:
            b.paragraph(err)
    title = doc_title or section_title
    return b.render_document(title, meta=meta)


def _render_deadlock_html(b: _HtmlBuilder, result: DeadlockAnalysisResult) -> None:
    b.heading(2, "Анализ TDEADLOCK", toc_level=1)
    for idx, case in enumerate(result.cases, 1):
        ev = case.event
        b.heading(2, f"Взаимоблокировка #{idx}", toc_level=2)
        b.table(
            ["Поле", "Значение"],
            [
                ["Время", format_ts(ev.ts)],
                ["Жертва (connect)", ev.connect_id],
                ["Сеанс", ev.session_id],
                ["Участник 2", case.culprit_connect_ids],
                ["Хост", ev.host],
                ["База", ev.process_name],
                ["Пользователь", ev.user],
                ["Тип", case.deadlock_type or ""],
            ],
        )
        b.context_section("Контекст", ev.context)
        if case.cross_matrix:
            b.context_section("Граф захвата ресурсов", case.cross_matrix)
        if case.timeline:
            b.raw('<p class="context-label">Хронология</p>')
            b.deadlock_timeline_table(case.timeline)
        elif case.timeline_text:
            b.context_section("Хронология", case.timeline_text)


def render_unified_html(
    result: UnifiedAnalysisResult,
    *,
    doc_title: str = "Сводный анализ проблем блокировок 1С",
    meta: str = "",
) -> str:
    s = result.summary
    summary_meta = meta or (
        f"TLOCK: {s['tlock_victims']} | TTIMEOUT: {s['ttimeout_victims']} | "
        f"TDEADLOCK: {s['tdeadlock_cases']}"
    )
    b = _HtmlBuilder()
    b.heading(2, "Сводка", toc_level=1)
    b.table(
        ["Тип", "Событий"],
        [
            ["TLOCK (ожидания)", str(s["tlock_victims"])],
            ["TTIMEOUT (таймауты)", str(s["ttimeout_victims"])],
            ["TDEADLOCK (взаимоблокировки)", str(s["tdeadlock_cases"])],
        ],
    )
    if result.tlock and result.tlock.victims:
        b.raw('<hr class="section">')
        b.heading(2, TLOCK_LABELS.title, toc_level=1)
        for idx, victim in enumerate(result.tlock.victims, 1):
            _render_victim_html(b, victim, idx)
    if result.ttimeout and result.ttimeout.victims:
        b.raw('<hr class="section">')
        b.heading(2, TTIMEOUT_LABELS.title, toc_level=1)
        for idx, victim in enumerate(result.ttimeout.victims, 1):
            _render_victim_html(b, victim, idx)
    if result.tdeadlock and result.tdeadlock.cases:
        b.raw('<hr class="section">')
        _render_deadlock_html(b, result.tdeadlock)
    return b.render_document(doc_title, meta=summary_meta)
