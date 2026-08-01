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


def test_history_matches_summary_when_stored_overall_was_email_critical():
    """Old DB rows stored Critical from email — History must recompute like the summary."""
    site = Website(
        id=1,
        url="https://www.apple.com",
        domain="www.apple.com",
        display_name="Apple",
    )
    result = HealthCheckResult(
        website_id=1,
        overall_status=HealthStatus.CRITICAL,  # legacy stored value
        risk_level=RiskLevel.HIGH,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.HEALTHY,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.CRITICAL,
        findings=[],
        response_time_ms=892,
        raw={},
    )
    detail = serialize_detail(site, result, [result], [])
    assert "looks healthy" in detail["summary"].lower()
    assert "Needs a fix" not in detail["history_html"]
    assert "Looks good" in detail["history_html"]


def test_serialize_unchecked_site():
    site = Website(
        id=1,
        url="https://example.com",
        domain="example.com",
        display_name="Example",
    )
    row = serialize_site_row(site, None)
    assert row["overall_label"] == "Not checked yet"
    assert row["last_checked_label"] == "Never"
    detail = serialize_detail(site, None, [], [])
    assert "Not checked yet" in detail["summary"]


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
        email_status=HealthStatus.CRITICAL,
        findings=[
            Finding("ssl", "Soon expiring", FindingStatus.INCORRECT, "30 days", "Renew"),
            Finding(
                "security",
                "HSTS",
                FindingStatus.MISSING,
                "ignored",
                "Ask a developer",
            ),
            Finding("dns", "Note", FindingStatus.INFO, "info only"),
            Finding(
                "spf",
                "SPF tip",
                FindingStatus.MISSING,
                "none",
                "Add SPF",
            ),
        ],
        response_time_ms=120,
        raw={
            "ssl": {"not_after": "2026-09-01T12:00:00+00:00", "days_remaining": 31},
            "whois": {"expiration_date": "2027-01-15T00:00:00+00:00", "days_remaining": 167},
        },
    )
    row = serialize_site_row(site, result)
    assert row["overall_label"] == "Worth a look"
    assert row["ssl_expires"] == "2026-09-01"
    assert row["ssl_expires_days"] == "31 days left"
    assert row["domain_expires"] == "2027-01-15"
    assert row["domain_expires_days"] == "167 days left"
    detail = serialize_detail(
        site,
        result,
        [result],
        [{"change": "updated", "rtype": "A", "old_value": "1.1.1.1", "new_value": "2.2.2.2"}],
    )
    assert "Example" in detail["summary"]
    assert "findings-table" in detail["findings_html"]
    assert "Soon expiring" in detail["findings_html"]
    assert "HSTS" not in detail["findings_html"]
    assert "SPF tip" not in detail["findings_html"]
    assert "Ask a developer" not in detail["findings_html"]
    assert "email_status" not in row
    assert "<table" in detail["history_html"]
    # History must match summary — not the old stored overall from email era.
    assert "Needs a fix" not in detail["history_html"]
    assert "Worth a look" in detail["history_html"]
    assert "1.1.1.1" in detail["changes_html"]
    assert row["ssl_label"] == "Worth a look"
    # Critical email must not flip the list Status column.
    assert row["overall_label"] == "Worth a look"
    assert "improve" in detail["summary"].lower()
