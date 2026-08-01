"""End-to-end import + Excel/CSV report download (no live network scan)."""

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
from whm.infrastructure.reports import build_csv_report, build_excel_report
from whm.infrastructure.repositories import (
    SqliteCustomerRepository,
    SqliteHealthCheckRepository,
    SqliteWebsiteRepository,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_import_example_clients_then_export_files(tmp_path: Path):
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
    assert len(result.added) == 6

    sites = websites.list_websites()
    demo = next(s for s in sites if "demo-shop" in s.domain)
    assert demo.display_name == "Demo Shop"

    saved = health.add(
        HealthCheckResult(
            website_id=demo.id,
            overall_status=HealthStatus.WARNING,
            risk_level=RiskLevel.MEDIUM,
            website_status=HealthStatus.HEALTHY,
            ssl_status=HealthStatus.HEALTHY,
            domain_status=HealthStatus.HEALTHY,
            dns_status=HealthStatus.HEALTHY,
            email_status=HealthStatus.WARNING,
            findings=[
                Finding(
                    "dns",
                    "DNS settings changed",
                    FindingStatus.INCORRECT,
                    "A record moved",
                    "Confirm the change was intentional",
                ),
                Finding(
                    "security",
                    "HSTS missing",
                    FindingStatus.MISSING,
                    "ignored category",
                    "should not appear in report",
                ),
                Finding(
                    "spf",
                    "SPF needs fixing",
                    FindingStatus.INCORRECT,
                    "ignored email category",
                    "should not appear",
                ),
            ],
        )
    )

    xname, xbytes = build_excel_report(demo, saved)
    cname, cbytes = build_csv_report(demo, saved)
    assert xname.endswith(".xlsx")
    assert cname.endswith(".csv")
    text = cbytes.decode("utf-8-sig")
    assert "DNS settings changed" in text
    assert "HSTS missing" not in text
    assert "SPF needs fixing" not in text
    assert extract_domain(demo.url) == demo.domain
