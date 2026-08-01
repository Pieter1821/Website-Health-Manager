"""Import website lists from Excel (.xlsx) or CSV."""

from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Optional

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Headers are normalized: "Client Website" -> "clientwebsite", "URL" -> "url".
# Only these fields are captured; any other columns are ignored.
URL_KEYS = ("url", "website", "domain", "site", "link", "address", "host", "webpage")
NAME_KEYS = ("display_name", "displayname", "name", "title", "label", "site_name")
CUSTOMER_KEYS = (
    "customer",
    "client",
    "clientwebsite",  # spreadsheet header: "Client Website"
    "clientname",
    "company",
    "account",
    "organisation",
    "organization",
)
DKIM_KEYS = ("dkim_selectors", "dkim", "selectors", "dkimselector")
INTERVAL_KEYS = ("check_interval", "interval", "schedule", "frequency")


@dataclass
class ImportRow:
    url: str
    display_name: str = ""
    customer: str = ""
    dkim_selectors: str = "s1,s2,em,default"
    check_interval: str = "manual"
    source_line: int = 0


@dataclass
class ImportResult:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"Added {len(self.added)}, skipped {len(self.skipped)}, "
            f"errors {len(self.errors)}"
        )


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _pick(row: dict[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        if key in row and row[key].strip():
            return row[key].strip()
    return ""


def _rows_from_matrix(matrix: list[list[str]]) -> list[ImportRow]:
    if not matrix:
        return []
    headers = [_norm_header(h) for h in matrix[0]]
    # If first row doesn't look like headers, treat column A as URL list.
    has_url_header = any(h in URL_KEYS for h in headers)
    rows: list[ImportRow] = []
    if not has_url_header:
        for idx, line in enumerate(matrix, start=1):
            if not line:
                continue
            value = (line[0] or "").strip()
            if not value or value.lower() in {"url", "website", "domain"}:
                continue
            rows.append(ImportRow(url=value, source_line=idx))
        return rows

    for idx, line in enumerate(matrix[1:], start=2):
        mapped = {
            headers[i]: (line[i] if i < len(line) else "").strip()
            for i in range(len(headers))
        }
        url = _pick(mapped, URL_KEYS)
        if not url:
            continue
        customer = _pick(mapped, CUSTOMER_KEYS)
        display_name = _pick(mapped, NAME_KEYS) or customer
        rows.append(
            ImportRow(
                url=url,
                display_name=display_name,
                customer=customer,
                dkim_selectors=_pick(mapped, DKIM_KEYS) or "s1,s2,em,default",
                check_interval=_pick(mapped, INTERVAL_KEYS) or "manual",
                source_line=idx,
            )
        )
    return rows


def parse_csv_bytes(data: bytes) -> list[ImportRow]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    matrix = [[cell.strip() for cell in row] for row in reader if any(c.strip() for c in row)]
    return _rows_from_matrix(matrix)


def _col_to_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    value = 0
    for ch in letters.group(0):
        value = value * 26 + (ord(ch) - 64)
    return value - 1


def parse_xlsx_bytes(data: bytes) -> list[ImportRow]:
    """Minimal XLSX reader (first sheet) — no openpyxl required."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                texts = [t.text or "" for t in si.findall(".//m:t", NS)]
                shared.append("".join(texts))

        sheet_name = "xl/worksheets/sheet1.xml"
        # Prefer first worksheet path from workbook if needed.
        if sheet_name not in archive.namelist():
            sheets = sorted(
                n for n in archive.namelist() if n.startswith("xl/worksheets/sheet")
            )
            if not sheets:
                raise ValueError("No worksheet found in Excel file")
            sheet_name = sheets[0]

        root = ET.fromstring(archive.read(sheet_name))
        matrix: list[list[str]] = []
        for row in root.findall("m:sheetData/m:row", NS):
            cells: dict[int, str] = {}
            for cell in row.findall("m:c", NS):
                ref = cell.attrib.get("r", "A1")
                idx = _col_to_index(ref)
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    texts = [t.text or "" for t in cell.findall(".//m:t", NS)]
                    raw = "".join(texts)
                else:
                    value_el = cell.find("m:v", NS)
                    if value_el is None or value_el.text is None:
                        raw = ""
                    elif cell_type == "s":
                        si = int(value_el.text)
                        raw = shared[si] if 0 <= si < len(shared) else ""
                    else:
                        raw = value_el.text
                cells[idx] = raw
            if not cells:
                continue
            width = max(cells) + 1
            line = [cells.get(i, "") for i in range(width)]
            if any(str(c).strip() for c in line):
                matrix.append([str(c).strip() for c in line])
    return _rows_from_matrix(matrix)


def parse_import_file(filename: str, data: bytes) -> list[ImportRow]:
    name = filename.lower().strip()
    if name.endswith(".csv") or name.endswith(".txt"):
        return parse_csv_bytes(data)
    if name.endswith(".xlsx"):
        return parse_xlsx_bytes(data)
    if name.endswith(".xls"):
        raise ValueError(
            "Old .xls format is not supported. Save the file as .xlsx or .csv in Excel."
        )
    # Sniff: zip/xlsx vs text/csv
    if data[:2] == b"PK":
        return parse_xlsx_bytes(data)
    return parse_csv_bytes(data)


def parse_import_path(path: str | Path) -> list[ImportRow]:
    file_path = Path(path)
    return parse_import_file(file_path.name, file_path.read_bytes())


def apply_import(
    rows: list[ImportRow],
    *,
    existing_domains: set[str],
    add_customer,
    add_website,
    extract_domain,
) -> ImportResult:
    """
    Import rows using injected service callables to keep this layer free of UI.

    add_customer(name) -> object with .id
    add_website(...) -> website with .domain
    extract_domain(url) -> str
    """
    result = ImportResult()
    seen = set(existing_domains)

    for row in rows:
        try:
            domain = extract_domain(row.url)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Line {row.source_line}: {exc}")
            continue
        if domain in seen:
            result.skipped.append(domain)
            continue
        customer_id = None
        if row.customer:
            customer_id = add_customer(row.customer).id
        try:
            site = add_website(
                url=row.url,
                display_name=row.display_name,
                customer_id=customer_id,
                dkim_selectors=row.dkim_selectors or "s1,s2,em,default",
                check_interval=row.check_interval or "manual",
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Line {row.source_line} ({row.url}): {exc}")
            continue
        seen.add(site.domain)
        result.added.append(site.domain)
    return result
