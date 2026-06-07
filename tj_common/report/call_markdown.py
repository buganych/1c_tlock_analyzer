"""Markdown report for CALL analysis."""

from __future__ import annotations

from tj_common.models_call import CallAnalysisResult
from tj_common.report.call_tables import md_table_section


def render_call_markdown(result: CallAnalysisResult) -> str:
    vis = result.visible_rows
    parts = [
        "# Анализ CALL",
        "",
        f"Всего событий: **{result.total_events}**",
        "",
        "## ТОП по длительности (сек)",
        "",
        *md_table_section(result.duration_rows, "сек", visible_n=vis),
        "## ТОП по CPU (сек)",
        "",
        *md_table_section(result.cpu_rows, "сек", visible_n=vis),
        "",
        "## ТОП по памяти (МБ)",
        "",
        *md_table_section(result.memory_rows, "МБ", visible_n=vis),
        "",
        "## ТОП по диску (всего нагрузка)",
        "",
        *md_table_section(result.disk_total_rows, "МБ", visible_n=vis),
        "## Топ по диску (пишущая нагрузка)",
        "",
        *md_table_section(result.disk_in_rows, "МБ", visible_n=vis),
        "## Топ по диску (читающая нагрузка)",
        "",
        *md_table_section(result.disk_out_rows, "МБ", visible_n=vis),
    ]
    return "\n".join(parts)
