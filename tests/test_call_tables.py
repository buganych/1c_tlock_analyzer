"""Tests for CALL report table splitting."""

from tj_common.models_call import CallTopRow
from tj_common.report.call_tables import md_table_section, split_rows


def _rows(n: int) -> list[CallTopRow]:
    return [
        CallTopRow(context=f"C{i}", count=i, avg=i, max=i, min=i, total=i * 2)
        for i in range(1, n + 1)
    ]


def test_split_rows_default_twenty():
    visible, hidden = split_rows(_rows(25))
    assert len(visible) == 20
    assert len(hidden) == 5


def test_md_table_section_collapsible():
    lines = md_table_section(_rows(25), "сек", visible_n=20)
    text = "\n".join(lines)
    assert "<details>" in text
    assert "Ещё 5" in text
    assert "C20" in text
    assert "C25" in text
