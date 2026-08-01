"""Serialization helpers for the web UI."""

from whm.domain.models import (
    Finding,
    FindingStatus,
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
    Website,
)
from whm.presentation.webapi import serialize_detail, serialize_site_row


def test_serialize_site_and_detail():
    site = Website(
        id=1,
        url="https://example.com",
        domain="example.com",
        display_name="Example",
    )
    result = HealthCheckResult(
        website_id=1,
        overall_status=HealthStatus.WARNING,
        risk_level=RiskLevel.MEDIUM,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.WARNING,
        domain_status=HealthStatus.UNKNOWN,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.HEALTHY,
        findings=[
            Finding("ssl", "Soon expiring", FindingStatus.INCORRECT, "30 days", "Renew"),
        ],
        response_time_ms=120,
        raw={
            "ssl": {"not_after": "2026-09-01T12:00:00+00:00", "days_remaining": 31},
            "whois": {"expiration_date": "2027-01-15T00:00:00+00:00", "days_remaining": 167},
        },
    )
    row = serialize_site_row(site, result)
    assert row["overall_label"] == "Needs attention"
    assert row["ssl_expires"] == "2026-09-01"
    assert row["ssl_expires_days"] == "31 days left"
    assert row["domain_expires"] == "2027-01-15"
    assert row["domain_expires_days"] == "167 days left"
    detail = serialize_detail(site, result, [result], [])
    assert "Example" in detail["summary"]
    assert "findings-table" in detail["findings_html"]
    assert "Soon expiring" in detail["findings_html"]
    assert "<table" in detail["history_html"]
    assert row["ssl_label"] == "Needs attention"
