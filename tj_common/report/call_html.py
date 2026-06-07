"""Interactive HTML report for CALL analysis."""

from __future__ import annotations

import html
import json
from dataclasses import asdict

from tj_common.models_call import CallAnalysisResult

_HTML_STYLES = """
body { font: 14px/1.5 Segoe UI, Arial, sans-serif; margin: 24px; color: #1f2328; }
h1, h2 { color: #0969da; }
.meta { color: #656d76; margin-bottom: 16px; }
.toolbar {
  margin: 16px 0 24px;
  padding: 12px 16px;
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  border-radius: 8px;
}
.toolbar label { font-weight: 600; margin-right: 8px; }
.toolbar input {
  width: min(480px, 100%);
  padding: 6px 10px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  font: inherit;
}
nav { margin-bottom: 24px; line-height: 1.8; }
nav a { color: #0969da; text-decoration: none; }
nav a:hover { text-decoration: underline; }
.call-section { margin-bottom: 32px; }
.table-wrap { overflow-x: auto; }
table.call-table {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0 8px;
}
table.call-table th, table.call-table td {
  border: 1px solid #d0d7de;
  padding: 6px 10px;
  text-align: left;
}
table.call-table th {
  background: #f6f8fa;
  white-space: nowrap;
}
table.call-table th.sortable {
  cursor: pointer;
  user-select: none;
}
table.call-table th.sortable:hover { background: #eef2f7; }
table.call-table th.sort-asc::after { content: " ▲"; color: #0969da; }
table.call-table th.sort-desc::after { content: " ▼"; color: #0969da; }
table.call-table td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
details.summary-more { margin: 8px 0 16px; }
details.summary-more summary {
  cursor: pointer;
  color: #0969da;
  font-size: 13px;
  padding: 4px 0;
  user-select: none;
}
details.summary-more summary:hover { text-decoration: underline; }
.section-empty { color: #656d76; font-style: italic; }
"""

_CALL_JS = """
(function () {
  const data = window.CALL_REPORT;
  const filterInput = document.getElementById('ctx-filter');
  const sortState = {};

  function cmp(a, b, col, dir) {
    const av = a[col];
    const bv = b[col];
    let res = 0;
    if (col === 'context') {
      res = String(av).localeCompare(String(bv), 'ru');
    } else {
      res = (Number(av) || 0) - (Number(bv) || 0);
    }
    return dir === 'asc' ? res : -res;
  }

  function sortRows(rows, sectionId) {
    const st = sortState[sectionId] || { col: 'avg', dir: 'desc' };
    return [...rows].sort((a, b) => cmp(a, b, st.col, st.dir));
  }

  function renderTable(section, rows, opts) {
    const st = sortState[section.id] || { col: 'avg', dir: 'desc' };
    const cols = [
      { key: 'context', label: 'Контекст', cls: '' },
      { key: 'avg', label: 'Средняя (' + section.unit + ')', cls: 'num' },
      { key: 'max', label: 'Максимальная (' + section.unit + ')', cls: 'num' },
      { key: 'min', label: 'Минимальная (' + section.unit + ')', cls: 'num' },
      { key: 'total', label: 'Всего (' + section.unit + ')', cls: 'num' },
      { key: 'count', label: 'Кол-во', cls: 'num' },
    ];
    const head = cols.map(c => {
      const active = st.col === c.key ? ' sort-' + st.dir : '';
      return '<th class="sortable' + active + '" data-section="' + section.id +
        '" data-col="' + c.key + '">' + c.label + '</th>';
    }).join('');
    const body = rows.map(r => {
      return '<tr>' + cols.map(c => {
        const val = r[c.key];
        const cls = c.cls ? ' class="' + c.cls + '"' : '';
        const text = c.key === 'context' ? escapeHtml(String(val)) : String(val);
        return '<td' + cls + '>' + text + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return '<div class="table-wrap"><table class="call-table"><thead><tr>' +
      head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderSection(section) {
    const host = document.getElementById('section-' + section.id);
    if (!host) return;
    const filter = (filterInput.value || '').trim().toLowerCase();
    let rows = section.rows;
    if (filter) {
      rows = rows.filter(r => r.context.toLowerCase().includes(filter));
    }
    rows = sortRows(rows, section.id);
    if (!rows.length) {
      host.innerHTML = '<p class="section-empty">нет строк по фильтру</p>';
      return;
    }
    let html = '';
    if (!filter && rows.length > data.visibleRows) {
      const visible = rows.slice(0, data.visibleRows);
      const hidden = rows.slice(data.visibleRows);
      html = renderTable(section, visible, {});
      html += '<details class="summary-more"><summary>Ещё ' + hidden.length +
        '</summary>' + renderTable(section, hidden, {}) + '</details>';
    } else {
      html = renderTable(section, rows, {});
      if (filter) {
        html = '<p class="section-meta">Показано ' + rows.length + ' из ' +
          section.rows.length + '</p>' + html;
      }
    }
    host.innerHTML = html;
    host.querySelectorAll('th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const sid = th.dataset.section;
        const col = th.dataset.col;
        const cur = sortState[sid] || { col: 'avg', dir: 'desc' };
        if (cur.col === col) {
          sortState[sid] = { col, dir: cur.dir === 'asc' ? 'desc' : 'asc' };
        } else {
          sortState[sid] = { col, dir: col === 'context' ? 'asc' : 'desc' };
        }
        data.sections.forEach(renderSection);
      });
    });
  }

  function renderAll() {
    data.sections.forEach(renderSection);
  }

  filterInput.addEventListener('input', renderAll);
  renderAll();
})();
"""


def _section_rows_payload(rows) -> list[dict]:
    return [asdict(r) for r in rows]


def render_call_html(result: CallAnalysisResult, *, meta: str = "") -> str:
    sections_meta = [
        ("duration", "ТОП по длительности (сек)", result.duration_rows, "сек"),
        ("cpu", "ТОП по CPU (сек)", result.cpu_rows, "сек"),
        ("memory", "ТОП по памяти (МБ)", result.memory_rows, "МБ"),
        ("disk-total", "ТОП по диску (всего нагрузка)", result.disk_total_rows, "МБ"),
        ("disk-in", "Топ по диску (пишущая нагрузка)", result.disk_in_rows, "МБ"),
        ("disk-out", "Топ по диску (читающая нагрузка)", result.disk_out_rows, "МБ"),
    ]
    report_data = {
        "visibleRows": result.visible_rows,
        "sections": [
            {
                "id": sid,
                "title": title,
                "unit": unit,
                "rows": _section_rows_payload(rows),
            }
            for sid, title, rows, unit in sections_meta
        ],
    }
    nav = "".join(
        f'<a href="#{sid}">{html.escape(title)}</a><br>'
        for sid, title, _, _ in sections_meta
    )
    section_hosts = "".join(
        f'<section class="call-section" id="{sid}">'
        f"<h2>{html.escape(title)}</h2>"
        f'<div id="section-{sid}"></div>'
        f"</section>"
        for sid, title, _, _ in sections_meta
    )
    meta_html = f'<p class="meta">{html.escape(meta)}</p>' if meta else ""
    data_json = json.dumps(report_data, ensure_ascii=False)
    data_json = data_json.replace("</", "<\\/")

    return (
        "<!DOCTYPE html><html lang='ru'><head>"
        "<meta charset='utf-8'><title>Анализ CALL</title>"
        f"<style>{_HTML_STYLES}</style></head><body>"
        "<h1>Анализ CALL</h1>"
        f"{meta_html}"
        f"<p>Всего событий: <strong>{result.total_events}</strong></p>"
        '<div class="toolbar">'
        '<label for="ctx-filter">Фильтр</label>'
        '<input id="ctx-filter" type="search" '
        'placeholder="Подстрока в контексте (во всех таблицах)" autocomplete="off">'
        "</div>"
        f"<nav>{nav}</nav>"
        f"{section_hosts}"
        f"<script>window.CALL_REPORT={data_json};</script>"
        f"<script>{_CALL_JS}</script>"
        "</body></html>"
    )
