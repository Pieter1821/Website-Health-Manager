"""Import website lists from Excel (.xlsx) or CSV."""

from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Headers are normalized: "Client Website" -> "clientwebsite", "URL" -> "url".
# Only these fields are captured; any other columns are ignored.
URL_KEYS = (
    "url",
    "website",
    "websiteurl",
    "websiteaddress",
    "domain",
    "site",
    "siteurl",
    "link",
    "address",
    "host",
    "webpage",
    "webaddress",
)
NAME_KEYS = (
    "display_name",
    "displayname",
    "websitename",
    "sitename",
    "name",
    "title",
    "label",
    "site_name",
)
CUSTOMER_KEYS = (
    "customer",
    "customername",
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

_HEADER_HINTS = frozenset(URL_KEYS) | frozenset(NAME_KEYS) | frozenset(CUSTOMER_KEYS)
_SKIP_TEXT_PREFIXES = (
    "fill in",
    "only ",
    "note:",
    "notes:",
    "instruction",
    "example:",
    "tip:",
    "leave other",
    "use import",
)


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
        base = (
            f"Added {len(self.added)}, skipped {len(self.skipped)}, "
            f"errors {len(self.errors)}"
        )
        if not self.errors:
            return base
        preview = "; ".join(self.errors[:3])
        more = f" (+{len(self.errors) - 3} more)" if len(self.errors) > 3 else ""
        return f"{base}. {preview}{more}"


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _pick(row: dict[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        if key in row and row[key].strip():
            return row[key].strip()
    return ""


def _find_header_row(matrix: list[list[str]]) -> Optional[int]:
    """Locate the header row by column labels — not by fixed position."""
    scan_limit = min(len(matrix), 30)
    best: Optional[int] = None
    best_score = 0
    for idx in range(scan_limit):
        norms = [_norm_header(c) for c in matrix[idx]]
        score = 0
        if any(h in URL_KEYS for h in norms):
            score += 3
        if any(h in NAME_KEYS or h in CUSTOMER_KEYS for h in norms):
            score += 2
        if any(h in DKIM_KEYS or h in INTERVAL_KEYS for h in norms):
            score += 1
        # Prefer rows that look like labels, not data domains.
        joined = " ".join(norms)
        if "http" in joined or any("." in (c or "") and " " not in (c or "") for c in matrix[idx]):
            # Likely a data row mistaken for header — only accept if strong header words.
            if score < 3:
                continue
        if score > best_score:
            best_score = score
            best = idx
    if best is not None and best_score >= 3:
        return best
    # Fallback: first row that has a URL-like header key alone.
    for idx in range(scan_limit):
        norms = [_norm_header(c) for c in matrix[idx]]
        if any(h in URL_KEYS for h in norms):
            return idx
    return None


def _looks_like_website(value: str) -> bool:
    """True if value could be a domain/URL — rejects instruction sentences."""
    text = (value or "").strip().strip("'\"")
    if not text:
        return False
    lower = text.lower()
    if any(lower.startswith(p) for p in _SKIP_TEXT_PREFIXES):
        return False
    if len(text) > 253:
        return False
    # Sentences / notes almost always contain spaces without a scheme.
    if " " in text and "://" not in text:
        return False
    candidate = text
    if "://" not in candidate:
        candidate = "https://" + candidate
    host = (urlparse(candidate).hostname or "").strip().lower().rstrip(".")
    if not host or "." not in host:
        return False
    # Reject header leftovers.
    if _norm_header(text) in _HEADER_HINTS | frozenset(URL_KEYS):
        return False
    return True


def parse_csv_bytes(data: bytes) -> list[ImportRow]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    numbered: list[tuple[int, list[str]]] = []
    for idx, row in enumerate(reader, start=1):
        cells = [cell.strip() for cell in row]
        if any(cells):
            numbered.append((idx, cells))
    return _rows_from_matrix_with_lines(numbered)


def _rows_from_matrix_with_lines(
    numbered: list[tuple[int, list[str]]],
) -> list[ImportRow]:
    matrix = [row for _, row in numbered]
    line_nos = [n for n, _ in numbered]
    if not matrix:
        return []
    header_idx = _find_header_row(matrix)
    rows: list[ImportRow] = []
    if header_idx is None:
        for i, line in enumerate(matrix):
            value = (line[0] or "").strip()
            if not value or _norm_header(value) in _HEADER_HINTS:
                continue
            if not _looks_like_website(value):
                continue
            rows.append(ImportRow(url=value, source_line=line_nos[i]))
        return rows

    headers = [_norm_header(h) for h in matrix[header_idx]]
    for i in range(header_idx + 1, len(matrix)):
        line = matrix[i]
        mapped = {
            headers[j]: (line[j] if j < len(line) else "").strip()
            for j in range(len(headers))
        }
        url = _pick(mapped, URL_KEYS)
        if not url:
            continue
        if any(url.lower().startswith(p) for p in _SKIP_TEXT_PREFIXES) or (
            " " in url and "://" not in url
        ):
            continue
        customer = _pick(mapped, CUSTOMER_KEYS)
        display_name = _pick(mapped, NAME_KEYS) or customer
        if display_name and any(
            display_name.lower().startswith(p) for p in _SKIP_TEXT_PREFIXES
        ):
            display_name = customer if customer and customer != display_name else ""
        rows.append(
            ImportRow(
                url=url,
                display_name=display_name,
                customer=customer,
                dkim_selectors=_pick(mapped, DKIM_KEYS) or "s1,s2,em,default",
                check_interval=_pick(mapped, INTERVAL_KEYS) or "manual",
                source_line=line_nos[i],
            )
        )
    return rows


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
        if sheet_name not in archive.namelist():
            sheets = sorted(
                n for n in archive.namelist() if n.startswith("xl/worksheets/sheet")
            )
            if not sheets:
                raise ValueError("No worksheet found in Excel file")
            sheet_name = sheets[0]

        root = ET.fromstring(archive.read(sheet_name))
        numbered: list[tuple[int, list[str]]] = []
        for row in root.findall("m:sheetData/m:row", NS):
            row_num = int(row.attrib.get("r", len(numbered) + 1))
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
            line = [str(cells.get(i, "")).strip() for i in range(width)]
            if any(line):
                numbered.append((row_num, line))
    return _rows_from_matrix_with_lines(numbered)


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
        if not (row.url or "").strip():
            continue
        if not _looks_like_website(row.url):
            snippet = row.url.replace("\n", " ").strip()
            if len(snippet) > 60:
                snippet = snippet[:57] + "…"
            result.errors.append(
                f"Row {row.source_line}: not a valid website address ({snippet!r})"
            )
            continue
        try:
            domain = extract_domain(row.url)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Row {row.source_line}: {exc}")
            continue
        if domain in seen:
            result.skipped.append(domain)
            continue
        customer_id = None
        customer_name = (row.customer or "").strip()
        if customer_name and any(
            customer_name.lower().startswith(p) for p in _SKIP_TEXT_PREFIXES
        ):
            customer_name = ""
        if customer_name:
            customer_id = add_customer(customer_name).id
        try:
            site = add_website(
                url=row.url,
                display_name=row.display_name,
                customer_id=customer_id,
                dkim_selectors=row.dkim_selectors or "s1,s2,em,default",
                check_interval=row.check_interval or "manual",
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Row {row.source_line} ({row.url}): {exc}")
            continue
        seen.add(site.domain)
        result.added.append(site.domain)
    return result
