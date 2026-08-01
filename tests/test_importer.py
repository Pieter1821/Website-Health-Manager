"""Excel/CSV import parsing tests."""

from pathlib import Path

from whm.infrastructure.importer import (
    apply_import,
    parse_csv_bytes,
    parse_import_file,
    parse_xlsx_bytes,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_parse_csv_with_headers():
    data = (
        b"website,customer,name\n"
        b"example.com,Acme,Example Site\n"
        b"https://contoso.org,Contoso,\n"
    )
    rows = parse_csv_bytes(data)
    assert len(rows) == 2
    assert rows[0].url == "example.com"
    assert rows[0].customer == "Acme"
    assert rows[0].display_name == "Example Site"


def test_parse_client_website_and_url_headers():
    """Match the user's spreadsheet: Client Website + URL (+ ignored extras)."""
    data = (
        b"Client Website,URL,Notes,Owner\n"
        b"ASHA Finance,https://www.asha.co.za,ignore me,Team A\n"
        b"LendGo Finance,https://www.lendgofinance.co.za,also ignore,Team B\n"
    )
    rows = parse_csv_bytes(data)
    assert len(rows) == 2
    assert rows[0].customer == "ASHA Finance"
    assert rows[0].display_name == "ASHA Finance"
    assert rows[0].url == "https://www.asha.co.za"
    assert rows[1].customer == "LendGo Finance"
    assert rows[1].url == "https://www.lendgofinance.co.za"


def test_example_test_clients_file_only_captures_client_and_url():
    path = EXAMPLES / "test-clients-import.csv"
    rows = parse_import_file(path.name, path.read_bytes())
    assert len(rows) == 7
    assert rows[0].customer == "ASHA Finance"
    assert rows[0].url == "https://www.asha.co.za"
    assert rows[1].customer == "LendGo Finance"
    assert all(r.url.startswith("http") for r in rows)
    # Extra columns (Notes/Owner/Priority) must not become URLs or customers.
    assert all("Team" not in r.url for r in rows)
    assert all("ignore" not in r.customer.lower() for r in rows)
    assert all(r.customer for r in rows)


def test_parse_csv_single_column():
    data = b"example.com\nfoo.co.za\n"
    rows = parse_csv_bytes(data)
    assert [r.url for r in rows] == ["example.com", "foo.co.za"]


def test_parse_xlsx_client_website_structure(tmp_path):
    import zipfile

    xlsx = tmp_path / "clients.xlsx"
    shared = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="6" uniqueCount="6">
  <si><t>Client Website</t></si>
  <si><t>URL</t></si>
  <si><t>Notes</t></si>
  <si><t>ASHA Finance</t></si>
  <si><t>https://www.asha.co.za</t></si>
  <si><t>should be ignored</t></si>
</sst>
"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>1</v></c>
      <c r="C1" t="s"><v>2</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>3</v></c>
      <c r="B2" t="s"><v>4</v></c>
      <c r="C2" t="s"><v>5</v></c>
    </row>
  </sheetData>
</worksheet>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""
    with zipfile.ZipFile(xlsx, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)

    rows = parse_xlsx_bytes(xlsx.read_bytes())
    assert len(rows) == 1
    assert rows[0].customer == "ASHA Finance"
    assert rows[0].url == "https://www.asha.co.za"
    assert rows[0].display_name == "ASHA Finance"


def test_parse_xlsx_roundtrip(tmp_path):
    import zipfile

    xlsx = tmp_path / "sites.xlsx"
    shared = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4" uniqueCount="4">
  <si><t>url</t></si><si><t>customer</t></si><si><t>example.com</t></si><si><t>Acme</t></si>
</sst>
"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
      <c r="B1" t="s"><v>1</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>2</v></c>
      <c r="B2" t="s"><v>3</v></c>
    </row>
  </sheetData>
</worksheet>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""
    with zipfile.ZipFile(xlsx, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)

    rows = parse_xlsx_bytes(xlsx.read_bytes())
    assert len(rows) == 1
    assert rows[0].url == "example.com"
    assert rows[0].customer == "Acme"


def test_apply_import_skips_duplicates():
    added = []

    class C:
        def __init__(self, name):
            self.id = 1

    class W:
        def __init__(self, domain):
            self.domain = domain

    result = apply_import(
        parse_csv_bytes(b"url\nexample.com\nexample.com\nnew.org\n"),
        existing_domains={"old.com"},
        add_customer=lambda name: C(name),
        add_website=lambda **kwargs: added.append(kwargs["url"])
        or W(kwargs["url"].replace("https://", "").split("/")[0]),
        extract_domain=lambda url: url.replace("https://", "").split("/")[0],
    )
    assert "example.com" in result.added
    assert result.skipped.count("example.com") == 1
    assert "new.org" in result.added


def test_apply_import_client_website_sheet_creates_customers():
    customers = []
    websites = []

    class C:
        def __init__(self, name):
            self.id = len(customers) + 1
            self.name = name

    class W:
        def __init__(self, domain):
            self.domain = domain

    path = EXAMPLES / "test-clients-import.csv"
    rows = parse_import_file(path.name, path.read_bytes())
    result = apply_import(
        rows,
        existing_domains=set(),
        add_customer=lambda name: customers.append(name) or C(name),
        add_website=lambda **kwargs: websites.append(kwargs)
        or W(
            kwargs["url"]
            .replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
        ),
        extract_domain=lambda url: url.replace("https://", "")
        .replace("http://", "")
        .split("/")[0],
    )
    assert result.errors == []
    assert len(result.added) == 7
    assert "ASHA Finance" in customers
    assert "LendGo Finance" in customers
    assert websites[0]["display_name"] == "ASHA Finance"
    assert websites[0]["url"] == "https://www.asha.co.za"
