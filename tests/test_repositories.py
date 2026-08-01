"""SQLite repository smoke tests using a temp database."""

from pathlib import Path

from whm.application.services import WebsiteService, extract_domain
from whm.domain.models import Finding, FindingStatus, HealthCheckResult, HealthStatus, RiskLevel
from whm.infrastructure.database import connect, initialize_database
from whm.infrastructure.repositories import (
    SqliteCustomerRepository,
    SqliteHealthCheckRepository,
    SqliteSettingsRepository,
    SqliteWebsiteRepository,
)


def test_extract_domain():
    assert extract_domain("https://www.Example.com/path") == "www.example.com"
    assert extract_domain("example.org") == "example.org"
    assert extract_domain("https://mybusiness.co.za/") == "mybusiness.co.za"


def test_extract_domain_rejects_bare_scheme():
    import pytest

    with pytest.raises(ValueError):
        extract_domain("https://")
    with pytest.raises(ValueError):
        extract_domain("http://")


def test_website_crud_and_health(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = connect(db)
    initialize_database(conn)
    customers = SqliteCustomerRepository(conn)
    websites = SqliteWebsiteRepository(conn)
    health = SqliteHealthCheckRepository(conn)
    settings = SqliteSettingsRepository(conn)

    assert settings.get("timeout_seconds") == "10"

    service = WebsiteService(customers, websites)
    customer = service.add_customer("Acme")
    site = service.add_website("https://example.com", customer_id=customer.id)
    assert site.id is not None
    assert site.domain == "example.com"

    result = HealthCheckResult(
        website_id=site.id,
        overall_status=HealthStatus.HEALTHY,
        risk_level=RiskLevel.LOW,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.WARNING,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.CRITICAL,
        findings=[
            Finding("spf", "SPF", FindingStatus.MISSING, "none"),
        ],
        response_time_ms=123.4,
    )
    saved = health.add(result)
    latest = health.latest_for_website(site.id)
    assert latest is not None
    assert latest.id == saved.id
    assert latest.findings[0].category == "spf"
    assert any(w.domain == "example.com" for w in service.search("exam"))
    assert any(w.domain == "example.com" for w in service.search("Acme"))

    settings.set("timeout_seconds", "25")
    assert settings.get("timeout_seconds") == "25"
    assert settings.get_all()["timeout_seconds"] == "25"

    orphan = HealthCheckResult(
        website_id=99999,
        overall_status=HealthStatus.HEALTHY,
        risk_level=RiskLevel.LOW,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.HEALTHY,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.HEALTHY,
    )
    import pytest

    with pytest.raises(ValueError):
        health.add(orphan)
