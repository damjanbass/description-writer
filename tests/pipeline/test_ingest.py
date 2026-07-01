"""Tests for Stage 1 ingestion (CSV/XLSX -> ProductRecord).

The XLSX cases build a minimal-but-valid .xlsx in `tmp_path` with stdlib
`zipfile` (see `_write_xlsx`) so the suite stays self-contained and needs no
openpyxl/sample binaries — it exercises exactly the parts our reader walks:
[Content_Types].xml, the workbook + its relationships, one worksheet, and the
shared-string table.
"""

import io
import types
import zipfile

import pytest

from pipeline.ingest import _read_zip_member, read_products

# --- Minimal XLSX fixture builder ----------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml"
    ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    Target="sharedStrings.xml"/>
</Relationships>"""

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _column_letter(index: int) -> str:
    """0-based column index -> A1 column letters (0->A, 26->AA)."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _build_shared_strings(grid: list[list[str]]) -> tuple[str, dict[str, int]]:
    """Build a sharedStrings.xml part and the value->index table it indexes.

    Mirrors how a real writer deduplicates every distinct non-empty cell into
    the string table; empty cells are not indexed (the worksheet omits them).
    """
    order: list[str] = []
    index_of: dict[str, int] = {}
    for row in grid:
        for value in row:
            if value and value not in index_of:
                index_of[value] = len(order)
                order.append(value)
    entries = "".join(f"<si><t>{value}</t></si>" for value in order)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{_NS}" count="{len(order)}" uniqueCount="{len(order)}">'
        f"{entries}</sst>"
    )
    return xml, index_of


def _build_sheet(grid: list[list[str]], index_of: dict[str, int]) -> str:
    """Build a sheet1.xml whose non-empty cells reference the string table.

    Empty cells are omitted entirely (the sparse layout real exporters
    produce), so this also exercises the reader's gap back-filling.
    """
    rows_xml = []
    for r, row in enumerate(grid, start=1):
        cells_xml = []
        for c, value in enumerate(row):
            if not value:
                continue
            ref = f"{_column_letter(c)}{r}"
            cells_xml.append(f'<c r="{ref}" t="s"><v>{index_of[value]}</v></c>')
        rows_xml.append(f'<row r="{r}">{"".join(cells_xml)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_NS}"><sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
    )


def _write_xlsx(path, grid: list[list[str]]) -> None:
    """Write a minimal valid .xlsx at `path` from a dense string grid."""
    shared_strings_xml, index_of = _build_shared_strings(grid)
    sheet_xml = _build_sheet(grid, index_of)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", _WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


# --- CSV ------------------------------------------------------------------


class TestReadCsv:
    def test_comma_delimited(self, tmp_path):
        path = tmp_path / "catalog.csv"
        path.write_text(
            "id,brand,color\n1,Samsung,crna\n2,Sony,bela\n", encoding="utf-8"
        )
        records = read_products(path)
        assert [r.product_id for r in records] == ["1", "2"]
        assert records[0].attributes == {"id": "1", "brand": "Samsung", "color": "crna"}

    def test_semicolon_delimited(self, tmp_path):
        # Serbian locale exports default to ';' (comma is the decimal sep).
        path = tmp_path / "catalog.csv"
        path.write_text(
            "id;brand;color\n10;Gigatron;plava\n", encoding="utf-8"
        )
        records = read_products(path)
        assert len(records) == 1
        assert records[0].product_id == "10"
        assert records[0].attributes == {
            "id": "10",
            "brand": "Gigatron",
            "color": "plava",
        }

    def test_utf8_bom_is_stripped_from_first_header(self, tmp_path):
        path = tmp_path / "bom.csv"
        # utf-8-sig writes a leading BOM that must not leak into "id".
        path.write_text("id,name\n7,Telefon\n", encoding="utf-8-sig")
        records = read_products(path)
        assert "id" in records[0].attributes
        assert records[0].product_id == "7"
        assert all(not key.startswith("﻿") for key in records[0].attributes)

    def test_headers_are_trimmed(self, tmp_path):
        path = tmp_path / "spaced.csv"
        path.write_text(" id , brand \n1, Samsung \n", encoding="utf-8")
        records = read_products(path)
        assert set(records[0].attributes) == {"id", "brand"}
        assert records[0].attributes["brand"] == "Samsung"

    def test_empty_cells_excluded_from_attributes_but_kept_in_raw_row(self, tmp_path):
        path = tmp_path / "gaps.csv"
        path.write_text("id,brand,color\n1,,crna\n", encoding="utf-8")
        records = read_products(path)
        record = records[0]
        assert record.attributes == {"id": "1", "color": "crna"}
        # raw_row keeps the empty cell verbatim for round-tripping/provenance.
        assert record.raw_row == {"id": "1", "brand": "", "color": "crna"}

    def test_single_column_file_has_no_delimiter(self, tmp_path):
        path = tmp_path / "one.csv"
        path.write_text("name\nTelefon\nTablet\n", encoding="utf-8")
        records = read_products(path)
        assert [r.attributes["name"] for r in records] == ["Telefon", "Tablet"]
        # No id column -> 1-based row index fallback.
        assert [r.product_id for r in records] == ["1", "2"]


class TestProductIdResolution:
    def test_sku_is_used_when_no_id_column(self, tmp_path):
        path = tmp_path / "sku.csv"
        path.write_text("sku,brand\nABC-1,Samsung\n", encoding="utf-8")
        records = read_products(path)
        assert records[0].product_id == "ABC-1"

    def test_id_header_match_is_case_insensitive(self, tmp_path):
        path = tmp_path / "upper.csv"
        path.write_text("SKU,brand\nXM5,Sony\n", encoding="utf-8")
        records = read_products(path)
        assert records[0].product_id == "XM5"

    def test_id_column_takes_priority_over_sku(self, tmp_path):
        path = tmp_path / "both.csv"
        path.write_text("sku,id\nXM5,99\n", encoding="utf-8")
        records = read_products(path)
        # "id" outranks "sku" even though it appears later in the file.
        assert records[0].product_id == "99"

    def test_row_index_fallback_when_no_id_header(self, tmp_path):
        path = tmp_path / "noid.csv"
        path.write_text("brand,color\nSamsung,crna\nSony,bela\n", encoding="utf-8")
        records = read_products(path)
        assert [r.product_id for r in records] == ["1", "2"]

    def test_empty_id_cell_falls_back_to_row_index(self, tmp_path):
        path = tmp_path / "blankid.csv"
        path.write_text("id,brand\n,Samsung\n5,Sony\n", encoding="utf-8")
        records = read_products(path)
        # Blank id -> row-index fallback; populated id is used as-is.
        assert records[0].product_id == "1"
        assert records[1].product_id == "5"


# --- XLSX -----------------------------------------------------------------


class TestReadXlsx:
    def test_basic_xlsx(self, tmp_path):
        path = tmp_path / "catalog.xlsx"
        _write_xlsx(
            path,
            [
                ["id", "brand", "color"],
                ["1", "Samsung", "crna"],
                ["2", "Sony", "bela"],
            ],
        )
        records = read_products(path)
        assert [r.product_id for r in records] == ["1", "2"]
        assert records[0].attributes == {
            "id": "1",
            "brand": "Samsung",
            "color": "crna",
        }
        assert records[1].attributes["brand"] == "Sony"

    def test_xlsx_sparse_empty_cells(self, tmp_path):
        # Middle cell empty -> omitted from the sheet XML; reader must keep the
        # column aligned and drop it only from `attributes`.
        path = tmp_path / "sparse.xlsx"
        _write_xlsx(
            path,
            [
                ["id", "brand", "color"],
                ["1", "", "crna"],
            ],
        )
        record = read_products(path)[0]
        assert record.attributes == {"id": "1", "color": "crna"}
        assert record.raw_row == {"id": "1", "brand": "", "color": "crna"}

    def test_xlsx_id_fallback_to_row_index(self, tmp_path):
        path = tmp_path / "noid.xlsx"
        _write_xlsx(path, [["brand", "color"], ["Samsung", "crna"]])
        assert read_products(path)[0].product_id == "1"

    def test_xlsx_headers_trimmed(self, tmp_path):
        path = tmp_path / "spaced.xlsx"
        _write_xlsx(path, [[" id ", " brand "], ["1", "Samsung"]])
        assert set(read_products(path)[0].attributes) == {"id", "brand"}


# --- Error handling -------------------------------------------------------


class TestErrors:
    def test_unsupported_extension_raises(self, tmp_path):
        path = tmp_path / "catalog.txt"
        path.write_text("id,brand\n1,Samsung\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported catalog extension"):
            read_products(path)

    def test_malformed_xlsx_raises_value_error(self, tmp_path):
        path = tmp_path / "broken.xlsx"
        path.write_text("this is not a zip", encoding="utf-8")
        with pytest.raises(ValueError, match="Malformed .xlsx"):
            read_products(path)

    def test_empty_csv_raises_value_error(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="Empty CSV"):
            read_products(path)


# --- Zip-member size guard (decompression-bomb defence) -------------------


class TestZipMemberSizeLimit:
    def _single_member_zip(self, path, name: str, data: bytes) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, data)

    def test_declared_size_over_limit_raises(self, tmp_path):
        # First guard: the central-directory file_size alone exceeds the limit,
        # so we refuse before inflating a single byte.
        path = tmp_path / "big.zip"
        self._single_member_zip(path, "payload.xml", b"x" * 4096)
        with zipfile.ZipFile(path) as archive:
            with pytest.raises(ValueError, match="Malformed .xlsx: member"):
                _read_zip_member(archive, "payload.xml", limit=1024)

    def test_lying_header_bomb_caught_by_streamed_check(self):
        # The advertised file_size can be forged small; the streamed byte count
        # is the real guarantee. A fake archive lets the first (getinfo) check
        # pass while the actual member content dwarfs the limit, so this
        # isolates and proves the chunked read enforces the cap on its own.
        class _LyingArchive:
            def getinfo(self, name):  # forged tiny declared size
                return types.SimpleNamespace(file_size=1)

            def open(self, name):
                return io.BytesIO(b"y" * 4096)  # real content over the limit

        with pytest.raises(ValueError, match="Malformed .xlsx: member"):
            _read_zip_member(_LyingArchive(), "payload.xml", limit=1024)

    def test_member_within_limit_reads_verbatim(self, tmp_path):
        path = tmp_path / "ok.zip"
        data = b"<xml>fine</xml>"
        self._single_member_zip(path, "payload.xml", data)
        with zipfile.ZipFile(path) as archive:
            assert _read_zip_member(archive, "payload.xml", limit=1024) == data

    def test_missing_member_raises_key_error(self, tmp_path):
        # Missing members must surface as KeyError so existing call sites keep
        # their optional-part handling.
        path = tmp_path / "empty.zip"
        self._single_member_zip(path, "payload.xml", b"data")
        with zipfile.ZipFile(path) as archive:
            with pytest.raises(KeyError):
                _read_zip_member(archive, "absent.xml", limit=1024)
