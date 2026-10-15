"""Format behavior that would otherwise shift dates or aggregate columns."""

from datetime import date
from io import BytesIO
from zipfile import ZipFile

import pytest

from research.historical_epidemics.scripts.format_parsers import parse_html_tables, parse_xlsx_rows


def _workbook(date_1904=False, formula=False):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("xl/workbook.xml", f'''<workbook
          xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
          <workbookPr date1904="{int(date_1904)}"/>
          <sheets><sheet name="Aggregate" sheetId="1" r:id="rId2"/>
          <sheet name="Empty" sheetId="2" r:id="rId1"/></sheets></workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''<Relationships
          xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
          <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="/xl/worksheets/sheet2.xml"/>
          </Relationships>''')
        archive.writestr("xl/styles.xml", '''<styleSheet
          xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>
          <cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs></styleSheet>''')
        archive.writestr("xl/sharedStrings.xml", '''<sst
          xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <si><r><t>Daily </t></r><r><t>total</t></r><rPh sb="0" eb="1"><t>phonetic</t></rPh></si></sst>''')
        archive.writestr("xl/worksheets/sheet1.xml", '''<worksheet
          xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>''')
        value = "<f>SUM(B1:B2)</f>" if formula else "<v>3.5</v>"
        archive.writestr("xl/worksheets/sheet2.xml", f'''<worksheet
          xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
          <row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><r><t>staff</t></r></is></c></row>
          <row r="3"><c r="A3" s="1"><v>1</v></c><c r="B3" t="b"><v>0</v></c><c r="D3">{value}</c></row>
          </sheetData></worksheet>''')
    return stream.getvalue()


def test_xlsx_preserves_sheet_order_sparse_cells_rich_text_and_date_system():
    rows = parse_xlsx_rows(_workbook())
    assert list(rows) == ["Aggregate", "Empty"]
    assert rows["Empty"] == []
    assert rows["Aggregate"] == [
        ["Daily total", None, "staff"], [], [date(1900, 1, 1), False, None, 3.5],
    ]
    assert parse_xlsx_rows(_workbook(date_1904=True))["Aggregate"][2][0] == date(1904, 1, 2)
    with pytest.raises(ValueError, match="no cached value"):
        parse_xlsx_rows(_workbook(formula=True))


def test_html_expands_multilevel_headers_and_preserves_blank_nested_text_cells():
    html = b'''<table><thead><tr><th rowspan="2"> </th><th colspan="2">On-<span>Campus</span></th></tr>
      <tr><th>Positive<br/>tests</th><th>Total&nbsp;tests</th></tr></thead><tbody>
      <tr><td>2020-01-01</td><td><strong>2</strong></td><td> 10 <script>ignore()</script></td></tr>
      <tr><td>2020-01-02</td><td></td><td><p>not</p><p>reported</p></td></tr></tbody></table>
      <table><tr><td>separate</td></tr></table>'''
    assert parse_html_tables(html) == [[
        ["", "On-Campus", "On-Campus"], ["", "Positive tests", "Total tests"],
        ["2020-01-01", "2", "10"], ["2020-01-02", "", "not reported"],
    ], [["separate"]]]


def test_html_rejects_uninterpretable_grid_instead_of_shifting_columns():
    for html, message in [
        (b'<table><tr><td rowspan="0">a</td></tr></table>', "positive integers"),
        (b'<table><tr><td rowspan="2">a</td></tr></table>', "past the explicit"),
        (b'<table><tr><td><table></table></td></tr></table>', "Nested"),
        (b'<table><tr><td>a</td></tr>', "Unclosed"),
    ]:
        with pytest.raises(ValueError, match=message):
            parse_html_tables(html)
