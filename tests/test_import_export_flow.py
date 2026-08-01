"""End-to-end import + report download bundle (no live network scan)."""

from pathlib import Path

from whm.application.services import WebsiteService, extract_domain
from whm.domain.models import (
    Finding,
    FindingStatus,
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
)
from whm.infrastructure.database import connect, initialize_database
from whm.infrastructure.reports import build_report_bundle
from whm.infrastructure.repositories import (
    SqliteCustomerRepository,
    SqliteHealthCheckRepository,
    SqliteWebsiteRepository,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_import_example_clients_then_export_zip(tmp_path: Path):
    conn = connect(tmp_path / "flow.db")
    initialize_database(conn)
    websites = WebsiteService(
        SqliteCustomerRepository(conn),
        SqliteWebsiteRepository(conn),
    )
    health = SqliteHealthCheckRepository(conn)

    path = EXAMPLES / "test-clients-import.csv"
    result = websites.import_list(path.name, path.read_bytes())
    assert result.errors == []
    assert len(result.added) == 7

    sites = websites.list_websites()
    assert len(sites) == 7
    asha = next(s for s in sites if "asha" in s.domain)
    assert asha.display_name == "ASHA Finance"

    # Fake a completed scan so export has content.
    saved = health.add(
        HealthCheckResult(
            website_id=asha.id,
            overall_status=HealthStatus.WARNING,
            risk_level=RiskLevel.MEDIUM,
            website_status=HealthStatus.HEALTHY,
            ssl_status=HealthStatus.HEALTHY,
            domain_status=HealthStatus.HEALTHY,
            dns_status=HealthStatus.HEALTHY,
            email_status=HealthStatus.WARNING,
            findings=[
                Finding(
                    "spf",
                    "SPF needs fixing",
                    FindingStatus.INCORRECT,
                    "Include sendgrid is missing",
                    "Add include:sendgrid.net",
                ),
                Finding(
                    "security",
                    "HSTS missing",
                    FindingStatus.MISSING,
                    "ignored category",
                    "should not appear in zip",
                ),
            ],
        )
    )
    import zipfile
    from io import BytesIO

    filename, payload = build_report_bundle(asha, saved)
    assert filename.endswith(".zip")
    assert payload[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        joined = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
    assert "SPF" in joined
    assert "HSTS missing" not in joined
    assert extract_domain(asha.url) == asha.domain
