"""Small, dependency-free readers for published historical aggregate tables.

XLSX formulas are never evaluated; a cached value is required. Date/time styles
are respected, including the workbook's 1904 date system. Merged XLSX cells
retain the stored top-left value and blanks rather than inventing values.

HTML rowspan/colspan cells are expanded into a rectangular grid, repeating the
cell text in every covered position. This also repeats multilevel headers;
callers must select observation rows themselves. Positive integer spans are
supported; rowspan=0 and nested tables raise ValueError rather than guessing.
"""

from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from io import BytesIO
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile


_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_BUILTIN_DATES = set(range(14, 23)) | set(range(27, 37)) | set(range(50, 59))
_BUILTIN_TIMES = {18, 19, 20, 21, 45, 47}


def _cell_text(element):
    """Read plain/rich strings without including phonetic annotations."""
    if element is None:
        return ""
    return "".join(
        node.text or ""
        for child in element
        for node in ([child] if child.tag == _MAIN + "t"
                     else child.findall(_MAIN + "t") if child.tag == _MAIN + "r"
                     else [])
    )


def _date_kind(number_format, custom_formats):
    if number_format == 46:
        return "duration"
    if number_format in _BUILTIN_TIMES:
        return "time"
    if number_format in _BUILTIN_DATES:
        return "datetime" if number_format == 22 else "date"
    code = custom_formats.get(number_format, "").lower()
    code = re.sub(r'"[^"]*"|\\.|_.|\*.', "", code)
    if re.search(r"\[(?:h+|m+|s+)\]", code):
        return "duration"
    code = re.sub(r"\[[^\]]*\]", "", code)
    has_date = bool(re.search(r"[yd]", code))
    has_time = bool(re.search(r"[hs]", code))
    if has_date:
        return "datetime" if has_time else "date"
    if has_time:
        return "time"
    if "m" in code:
        return "date"
    return None


def _excel_date(value, kind, date_1904):
    if kind == "duration":
        return timedelta(days=value)
    if kind == "time":
        milliseconds = round((value % 1) * 86400000) % 86400000
        return (datetime(2000, 1, 1) + timedelta(milliseconds=milliseconds)).time()
    # Excel's fictitious 1900-02-29 is mapped to 1900-02-28, as in common
    # spreadsheet readers; dates before the fictitious leap day need an offset.
    base = datetime(1904, 1, 1) if date_1904 else datetime(1899, 12, 30)
    adjusted = value + (1 if not date_1904 and 0 < value < 60 else 0)
    result = base + timedelta(milliseconds=round(adjusted * 86400000))
    if kind == "date" and result.time() == time():
        return result.date()
    return result


def _column_index(reference):
    match = re.fullmatch(r"([A-Za-z]+)[1-9][0-9]*", reference)
    if not match:
        raise ValueError(f"Invalid XLSX cell reference: {reference!r}")
    column = 0
    for letter in match.group(1).upper():
        column = column * 26 + ord(letter) - ord("A") + 1
    return column - 1


def parse_xlsx_rows(raw: bytes) -> dict[str, list[list[object]]]:
    """Return worksheets in workbook order, preserving sparse rows/cells.

    Cells become str, int, float, bool, date, datetime, time, timedelta or None.
    Excel error cells remain their error text. Date recognition uses styles,
    never column names or value ranges. Missing formula caches raise ValueError.
    """
    with ZipFile(BytesIO(raw)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        properties = workbook.find(_MAIN + "workbookPr")
        date_1904 = properties is not None and properties.get("date1904") in {"1", "true"}
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.get("Id"): relation.get("Target")
            for relation in relationships
            if relation.get("Type", "").endswith("/worksheet")
            and relation.get("TargetMode") != "External"
        }
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [_cell_text(item) for item in
                       ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        styles = []
        if "xl/styles.xml" in archive.namelist():
            style_root = ET.fromstring(archive.read("xl/styles.xml"))
            formats = {
                int(item.get("numFmtId")): item.get("formatCode", "")
                for item in style_root.findall(_MAIN + "numFmts/" + _MAIN + "numFmt")
            }
            styles = [
                _date_kind(int(item.get("numFmtId", "0")), formats)
                for item in style_root.findall(_MAIN + "cellXfs/" + _MAIN + "xf")
            ]

        result = {}
        for sheet in workbook.findall(_MAIN + "sheets/" + _MAIN + "sheet"):
            target = targets.get(sheet.get(_REL + "id"))
            if target is None:
                continue
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join("xl", target))
            root = ET.fromstring(archive.read(path))
            rows = []
            for row in root.findall(_MAIN + "sheetData/" + _MAIN + "row"):
                row_number = int(row.get("r", len(rows) + 1))
                if row_number <= len(rows):
                    raise ValueError("XLSX rows must have increasing positive indices")
                while len(rows) < row_number - 1:
                    rows.append([])
                values = []
                for cell in row.findall(_MAIN + "c"):
                    reference = cell.get("r")
                    column = _column_index(reference) if reference else len(values)
                    if column < len(values):
                        raise ValueError("XLSX cells must have increasing column indices")
                    values.extend([None] * (column - len(values)))
                    kind = cell.get("t", "n")
                    value_element = cell.find(_MAIN + "v")
                    value = value_element.text if value_element is not None else None
                    if kind == "inlineStr":
                        value = _cell_text(cell.find(_MAIN + "is"))
                    elif value is None:
                        if cell.find(_MAIN + "f") is not None:
                            raise ValueError(f"XLSX formula has no cached value: {reference}")
                    elif kind == "s":
                        value = strings[int(value)]
                    elif kind == "b":
                        if value not in {"0", "1"}:
                            raise ValueError(f"Invalid XLSX boolean: {value!r}")
                        value = value == "1"
                    elif kind == "d":
                        value = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
                    elif kind not in {"str", "e"}:
                        number = float(value)
                        style_index = int(cell.get("s", "0"))
                        if cell.get("s") is not None and style_index >= len(styles):
                            raise ValueError(f"Unknown XLSX style index: {style_index}")
                        date_kind = styles[style_index] if style_index < len(styles) else None
                        value = _excel_date(number, date_kind, date_1904) if date_kind else (
                            int(number) if number.is_integer() else number)
                    values.append(value)
                rows.append(values)
            result[sheet.get("name")] = rows
        return result


def _expand_spans(rows):
    occupied = {}
    for row_index, cells in enumerate(rows):
        column = 0
        for text, rowspan, colspan in cells:
            while (row_index, column) in occupied:
                column += 1
            for row_offset in range(rowspan):
                for column_offset in range(colspan):
                    position = (row_index + row_offset, column + column_offset)
                    if position in occupied:
                        raise ValueError("Overlapping HTML table spans")
                    occupied[position] = text
            column += colspan
    if any(row >= len(rows) for row, _ in occupied):
        raise ValueError("HTML rowspan extends past the explicit table rows")
    width = max((column + 1 for _, column in occupied), default=0)
    return [[occupied.get((row, column), "") for column in range(width)]
            for row in range(len(rows))]


class _TableParser(HTMLParser):
    _BLOCKS = {"p", "div", "li", "section", "article", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.rows = None
        self.row = None
        self.parts = None
        self.spans = (1, 1)
        self.suppressed = 0

    def _finish_cell(self):
        if self.parts is not None:
            self.row.append((" ".join("".join(self.parts).split()), *self.spans))
            self.parts = None

    def _finish_row(self):
        self._finish_cell()
        if self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.rows is not None:
                raise ValueError("Nested HTML tables are not supported")
            self.rows = []
        elif self.rows is not None:
            if tag in {"script", "style"}:
                self.suppressed += 1
            elif self.suppressed:
                return
            elif tag == "tr":
                self._finish_row()
                self.row = []
            elif tag in {"td", "th"}:
                self._finish_cell()
                if self.row is None:
                    self.row = []
                attributes = dict(attrs)
                try:
                    self.spans = tuple(int(attributes.get(name, "1")) for name in ("rowspan", "colspan"))
                except (TypeError, ValueError) as error:
                    raise ValueError("HTML spans must be positive integers") from error
                if any(span < 1 for span in self.spans):
                    raise ValueError("HTML spans must be positive integers; rowspan=0 is unsupported")
                self.parts = []
            elif self.parts is not None and (tag == "br" or tag in self._BLOCKS):
                self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.rows is None:
            return
        if tag in {"script", "style"}:
            self.suppressed = max(0, self.suppressed - 1)
        elif self.suppressed:
            return
        elif tag in {"td", "th"}:
            self._finish_cell()
        elif tag == "tr":
            self._finish_row()
        elif tag == "table":
            self._finish_row()
            self.tables.append(_expand_spans(self.rows))
            self.rows = None
        elif self.parts is not None and tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if self.parts is not None and not self.suppressed:
            self.parts.append(data)


def parse_html_tables(raw: bytes) -> list[list[list[str]]]:
    """Read UTF-8 HTML tables, preserving blank cells and expanding spans.

    thead/tbody/tfoot do not discard rows. Whitespace and br/block separators
    normalize to one space; inline nested tags retain their text. Ragged rows
    are padded with empty strings. No header or data type is inferred.
    """
    parser = _TableParser()
    parser.feed(raw.decode("utf-8-sig"))
    parser.close()
    if parser.rows is not None:
        raise ValueError("Unclosed HTML table")
    return parser.tables
