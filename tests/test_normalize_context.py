from tj_common.report.event_report import normalize_context


def test_normalize_context_strips_blank_lines():
    raw = "\r\nModule.A : 1 : X();\r\n\r\n\tModule.B : 2 : Y();\r\n"
    assert normalize_context(raw) == "Module.A : 1 : X();\n\tModule.B : 2 : Y();"
