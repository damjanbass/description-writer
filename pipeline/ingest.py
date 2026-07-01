"""Stage 1 — ingestion. CSV/XLSX catalog file -> list[ProductRecord].

IMPLEMENTATION CONTRACT (do not change the public signature below):

`read_products(path)` reads a `.csv` or `.xlsx` file selected by extension
and returns one `ProductRecord` per data row.

- First row is the header; subsequent rows are products.
- `attributes` = only the non-empty cells, keyed by header name (trimmed).
- `raw_row` = the full original row, header-keyed, including empty cells.
- `product_id` = the value of the first header that case-insensitively matches
  one of {"id", "sku", "product_id", "mpn", "ean"}; if none is present, fall
  back to the 1-based row index as a string. Never return an empty id.
- CSV: stdlib `csv`; sniff delimiter (`,` or `;` — Serbian exports often use
  `;`); decode UTF-8 with BOM tolerance (`utf-8-sig`).
- XLSX: stdlib only (no openpyxl). An .xlsx is a zip; parse the first
  worksheet via `zipfile` + `xml.etree.ElementTree`, resolving shared strings
  from xl/sharedStrings.xml. Read cell values as text.
- Raise a clear `ValueError` for unsupported extensions and malformed files.

Why stdlib-first (no pandas/openpyxl): this stage is the only hard I/O
boundary of the pipeline and runs before any correctness guarantee applies.
Keeping it on `csv` + `zipfile` + `ElementTree` means a catalog file can be
ingested on a vanilla Python 3.11 with zero install, and the "flag, don't
guess" rule is enforced at the door — a delimiter we cannot sniff or a zip
we cannot parse is a `ValueError`, not a half-read row that quietly poisons
generation downstream.

Tests go in tests/pipeline/test_ingest.py. Cover: CSV comma + semicolon,
BOM, id-column detection + row-index fallback, empty-cell handling, a minimal
hand-built XLSX, and the unsupported-extension error.
"""

from __future__ import annotations

import csv
import os
import re
import zipfile
from xml.etree import ElementTree

from pipeline.types import ProductRecord

# Headers (matched case-insensitively, after trimming) whose value identifies
# the product. Ordered by preference: a real catalog id beats an SKU beats a
# manufacturer/barcode code. The first header present in the file wins, so a
# sheet with both "id" and "sku" keys off "id".
_ID_HEADERS: tuple[str, ...] = ("id", "sku", "product_id", "mpn", "ean")

# SpreadsheetML (OOXML) main namespace. Every element in a worksheet,
# sharedStrings and workbook part is qualified with it, so we strip it off
# tag names rather than carry it through every lookup.
_OOXML_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# An A1-style cell reference -> its column letters (e.g. "AB12" -> "AB"). The
# trailing row number is discarded; column order is what we need to slot a
# possibly-sparse row back into header positions.
_CELL_COLUMN_RE = re.compile(r"^([A-Z]+)")

# Upper bound on the decompressed size of any single zip member we read from an
# .xlsx. An .xlsx is untrusted input at the I/O boundary, and `zipfile` will
# happily inflate a "zip bomb" member far larger than the archive on disk into
# memory. We cap each member at 64 MB and refuse anything larger — both by the
# size the zip header advertises and by the bytes we actually inflate, because
# the advertised `file_size` can be forged.
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


def read_products(path: str | os.PathLike[str]) -> list[ProductRecord]:
    """Read a `.csv` or `.xlsx` catalog into `ProductRecord`s, one per data row.

    Extension-dispatched (not content-sniffed): the caller names the format by
    its suffix, and anything else is an explicit `ValueError` rather than a
    guess. Both readers funnel into `_rows_to_records`, so id detection,
    attribute filtering and raw-row capture behave identically regardless of
    source format.
    """
    path = os.fspath(path)
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".csv":
        header, rows = _read_csv_rows(path)
    elif suffix == ".xlsx":
        header, rows = _read_xlsx_rows(path)
    else:
        raise ValueError(
            f"Unsupported catalog extension {suffix!r} for {path!r}: "
            "expected '.csv' or '.xlsx'."
        )
    return _rows_to_records(header, rows)


def _read_csv_rows(path: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, data_rows) from a CSV file.

    Decoded as `utf-8-sig` so a leading BOM (common in Excel-exported Serbian
    catalogs) is stripped from the first header rather than smuggled into the
    first column name. The delimiter is sniffed between comma and semicolon —
    Serbian locale exports default to `;` because the comma is the decimal
    separator — and a file we cannot classify is a `ValueError`, never a
    silent fallback that would merge columns.
    """
    with open(path, encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        if not sample.strip():
            raise ValueError(f"Empty CSV file: {path!r}.")
        delimiter = _sniff_delimiter(sample, path)
        handle.seek(0)
        reader = csv.reader(handle, delimiter=delimiter)
        rows = [list(row) for row in reader]

    # A BOM only gets stripped by utf-8-sig when it is the very first byte of
    # the stream; csv.reader does not touch it, so the header is already clean.
    header = [cell.strip() for cell in rows[0]]
    return header, rows[1:]


def _sniff_delimiter(sample: str, path: str) -> str:
    """Pick ',' or ';' for a CSV sample, preferring `csv.Sniffer`.

    We constrain the candidate set to the two delimiters this pipeline
    supports so the Sniffer cannot wander off to tabs or pipes on a noisy
    sample. If the Sniffer fails outright (e.g. a single-column file with no
    delimiter at all) we fall back to whichever candidate actually occurs, and
    default to comma for a genuinely delimiter-free single column.
    """
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        return dialect.delimiter
    except csv.Error:
        # Single-column / ambiguous sample: choose the delimiter that is
        # present, else comma. This never silently merges columns because a
        # sample with neither delimiter is, by definition, one column wide.
        if ";" in sample and "," not in sample:
            return ";"
        return ","


def _read_zip_member(
    archive: zipfile.ZipFile, name: str, limit: int = _MAX_MEMBER_BYTES
) -> bytes:
    """Read one zip member fully, refusing members that inflate past `limit`.

    Guards the .xlsx boundary against decompression bombs. `archive.read()` is
    unbounded, so a crafted member can inflate to gigabytes from a tiny archive
    and exhaust memory. We enforce `limit` twice: first against the size the
    central directory advertises (`getinfo().file_size`), then against the bytes
    we actually inflate — the header value can be forged small, so the streamed
    check is the real guarantee. Both breaches raise `ValueError` in the file's
    "Malformed .xlsx: ..." style. Missing members raise `KeyError` (from
    `getinfo`), preserving each call site's existing handling.
    """
    if archive.getinfo(name).file_size > limit:
        raise ValueError(
            f"Malformed .xlsx: member {name!r} exceeds the {limit}-byte size limit."
        )
    chunk_size = 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    with archive.open(name) as member:
        while True:
            chunk = member.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError(
                    f"Malformed .xlsx: member {name!r} exceeds the "
                    f"{limit}-byte size limit."
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _read_xlsx_rows(path: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, data_rows) from the first worksheet of an .xlsx file.

    An .xlsx is a zip of XML parts. We read it with `zipfile` +
    `ElementTree` (no openpyxl) by: (1) resolving the first sheet's part via
    the workbook relationships, (2) loading the shared-string table, then
    (3) walking the sheet's rows and slotting each cell into its A1 column so
    that gaps left by omitted empty cells are preserved as empty strings.
    Anything structurally wrong — not a zip, missing worksheet, bad XML — is
    re-raised as a `ValueError` so ingestion fails loudly at the boundary.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _read_shared_strings(archive)
            sheet_name = _first_worksheet_name(archive)
            sheet_xml = _read_zip_member(archive, sheet_name)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Malformed .xlsx (not a valid zip): {path!r}.") from exc
    except KeyError as exc:
        raise ValueError(f"Malformed .xlsx (missing worksheet part): {path!r}.") from exc

    try:
        sheet_root = ElementTree.fromstring(sheet_xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Malformed .xlsx worksheet XML: {path!r}.") from exc

    matrix = _worksheet_matrix(sheet_root, shared_strings)
    if not matrix:
        raise ValueError(f"Empty .xlsx worksheet (no rows): {path!r}.")
    header = [cell.strip() for cell in matrix[0]]
    return header, matrix[1:]


def _first_worksheet_name(archive: zipfile.ZipFile) -> str:
    """Resolve the zip path of the workbook's first worksheet part.

    The reliable route is workbook.xml -> its `r:id` ordering -> the matching
    relationship target in workbook.xml.rels. We honour the `<sheets>` order
    (the user-visible first tab), then fall back to `xl/worksheets/sheet1.xml`
    if the relationship plumbing is absent, which keeps minimal hand-built
    files (and our own test fixtures) working.
    """
    rels = _workbook_rels(archive)
    try:
        workbook_root = ElementTree.fromstring(
            _read_zip_member(archive, "xl/workbook.xml")
        )
    except (KeyError, ElementTree.ParseError):
        workbook_root = None

    if workbook_root is not None and rels:
        sheets = workbook_root.find(f"{{{_OOXML_NS}}}sheets")
        if sheets is not None:
            for sheet in sheets:
                rid = sheet.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                target = rels.get(rid) if rid is not None else None
                if target is not None:
                    return _normalize_part_path(target)

    if "xl/worksheets/sheet1.xml" in archive.namelist():
        return "xl/worksheets/sheet1.xml"
    raise ValueError("Malformed .xlsx: could not locate the first worksheet.")


def _workbook_rels(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map each relationship id in xl/_rels/workbook.xml.rels to its target.

    Returns an empty mapping when the rels part is absent or unreadable; the
    caller treats that as "fall back to the conventional sheet1.xml path".
    """
    try:
        rels_root = ElementTree.fromstring(
            _read_zip_member(archive, "xl/_rels/workbook.xml.rels")
        )
    except (KeyError, ElementTree.ParseError):
        return {}
    return {
        rel.get("Id"): rel.get("Target")
        for rel in rels_root
        if rel.get("Id") and rel.get("Target")
    }


def _normalize_part_path(target: str) -> str:
    """Turn a workbook-relative relationship target into a zip member path.

    Relationship targets are relative to `xl/` (e.g. "worksheets/sheet1.xml")
    and may be written absolute ("/xl/worksheets/sheet1.xml"); normalize both
    to the bare zip path the archive is keyed by.
    """
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Load xl/sharedStrings.xml into an index-ordered list of strings.

    Most text in an .xlsx is deduplicated into this table and referenced by a
    cell whose `t="s"` and `<v>` is the index. Each `<si>` entry is either a
    single `<t>` or a run of `<r><t>...` pieces (rich text) we concatenate.
    A workbook with no string table (all-numeric) simply has no part here, so
    an absence is normal and yields an empty list.
    """
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    try:
        root = ElementTree.fromstring(
            _read_zip_member(archive, "xl/sharedStrings.xml")
        )
    except ElementTree.ParseError as exc:
        raise ValueError("Malformed .xlsx: unreadable sharedStrings.xml.") from exc

    strings: list[str] = []
    for si in root.findall(f"{{{_OOXML_NS}}}si"):
        strings.append(_collect_text(si))
    return strings


def _collect_text(element: ElementTree.Element) -> str:
    """Concatenate every `<t>` descendant's text under a shared-string node.

    Handles both the plain `<si><t>foo</t></si>` form and the rich-text
    `<si><r><t>foo</t></r><r><t>bar</t></r></si>` form by gathering all `<t>`
    nodes in document order.
    """
    parts = [
        node.text or "" for node in element.iter(f"{{{_OOXML_NS}}}t")
    ]
    return "".join(parts)


def _worksheet_matrix(
    sheet_root: ElementTree.Element, shared_strings: list[str]
) -> list[list[str]]:
    """Flatten a worksheet's `<sheetData>` into a dense list-of-rows matrix.

    Cells carry an A1 reference (`r="B2"`); empty cells are frequently omitted
    entirely, so we place each cell at its column index and back-fill the gaps
    with empty strings. Every row is then padded to the widest row so columns
    line up with their headers — the contract needs the full row, empties and
    all, for `raw_row`.
    """
    sheet_data = sheet_root.find(f"{{{_OOXML_NS}}}sheetData")
    if sheet_data is None:
        return []

    rows: list[list[str]] = []
    for row in sheet_data.findall(f"{{{_OOXML_NS}}}row"):
        cells: dict[int, str] = {}
        next_index = 0
        for cell in row.findall(f"{{{_OOXML_NS}}}c"):
            reference = cell.get("r")
            index = _column_index(reference) if reference else next_index
            cells[index] = _cell_text(cell, shared_strings)
            next_index = index + 1
        if not cells:
            rows.append([])
            continue
        width = max(cells) + 1
        rows.append([cells.get(i, "") for i in range(width)])

    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def _column_index(reference: str) -> int:
    """Zero-based column index for an A1 cell reference (A->0, B->1, AA->26).

    Bijective base-26 over the leading letters; the row digits are ignored
    because the sheet walk already iterates rows in order.
    """
    match = _CELL_COLUMN_RE.match(reference)
    letters = match.group(1) if match else ""
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    """Resolve one worksheet cell `<c>` to its display text.

    Three forms matter: `t="s"` shared-string cells dereference into the
    shared-string table by integer index; `t="inlineStr"` cells carry their
    text inline under `<is>`; everything else (numbers, booleans, formula
    results) uses the literal `<v>` text, which is exactly the "read values as
    text" the contract asks for. An out-of-range shared-string index is a
    structural corruption and raised as a `ValueError`.
    """
    cell_type = cell.get("t")
    if cell_type == "s":
        value = cell.find(f"{{{_OOXML_NS}}}v")
        if value is None or value.text is None:
            return ""
        try:
            return shared_strings[int(value.text)]
        except (ValueError, IndexError) as exc:
            raise ValueError(
                f"Malformed .xlsx: shared-string index {value.text!r} out of range."
            ) from exc
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{_OOXML_NS}}}is")
        return _collect_text(inline) if inline is not None else ""
    value = cell.find(f"{{{_OOXML_NS}}}v")
    return value.text if value is not None and value.text is not None else ""


def _rows_to_records(
    header: list[str], rows: list[list[str]]
) -> list[ProductRecord]:
    """Build one `ProductRecord` per data row against a shared header.

    Shared by both readers so id detection, the non-empty `attributes` filter
    and the verbatim `raw_row` are format-agnostic. The id column is located
    once (first header matching `_ID_HEADERS`), and the 1-based data-row index
    is the fallback id so every record is guaranteed a non-empty `product_id`,
    even for an unkeyed catalog.
    """
    if not header:
        raise ValueError("Catalog has no header row.")
    id_column = _id_column_index(header)

    records: list[ProductRecord] = []
    for offset, row in enumerate(rows, start=1):
        raw_row = _row_to_dict(header, row)
        attributes = {key: value for key, value in raw_row.items() if value}
        product_id = ""
        if id_column is not None:
            product_id = row[id_column].strip() if id_column < len(row) else ""
        if not product_id:
            product_id = str(offset)
        records.append(
            ProductRecord(
                product_id=product_id, attributes=attributes, raw_row=raw_row
            )
        )
    return records


def _id_column_index(header: list[str]) -> int | None:
    """Index of the first header that case-insensitively matches `_ID_HEADERS`.

    Preference follows `_ID_HEADERS` order, but a header appearing earlier in
    the file at the same preference tier still wins by position — we scan the
    candidates in priority order and return the earliest column for the
    highest-priority name present.
    """
    lowered = [cell.strip().lower() for cell in header]
    for candidate in _ID_HEADERS:
        if candidate in lowered:
            return lowered.index(candidate)
    return None


def _row_to_dict(header: list[str], row: list[str]) -> dict[str, str]:
    """Zip a data row to its header, tolerating ragged rows in both directions.

    Cells past the header width are dropped (no column to name them); headers
    past the row width map to empty strings. Cell text is trimmed so trailing
    delimiter whitespace does not masquerade as content in `attributes`.
    """
    record: dict[str, str] = {}
    for index, name in enumerate(header):
        value = row[index].strip() if index < len(row) else ""
        record[name] = value
    return record
