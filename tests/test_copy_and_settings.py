"""Plain-language copy + settings field registry."""

from whm.domain.models import (
    Finding,
    FindingStatus,
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
)
from whm.presentation.copy import (
    category_plain,
    category_tip,
    finding_plain,
    overall_summary,
    overall_why,
    status_plain,
)
from whm.presentation.settings_fields import SETTINGS_FIELDS


def _result(**statuses):
    defaults = dict(
        website_id=1,
        overall_status=HealthStatus.WARNING,
        risk_level=RiskLevel.MEDIUM,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.HEALTHY,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.HEALTHY,
        findings=[],
    )
    defaults.update(statuses)
    return HealthCheckResult(**defaults)


def test_status_and_finding_plain():
    assert status_plain(HealthStatus.CRITICAL) == "Needs a fix"
    assert status_plain(HealthStatus.WARNING) == "Worth a look"
    assert finding_plain(FindingStatus.MISSING) == "Not set up"
    assert finding_plain(FindingStatus.INCORRECT) == "Review"
    assert category_plain("dkim") == "Email signature (DKIM)"
    assert "domain" in category_tip("dkim").lower() or "stamp" in category_tip("dkim").lower()
    assert "attention" in category_tip("unknown_thing").lower()


def test_overall_why_edges():
    healthy = _result(overall_status=HealthStatus.HEALTHY)
    assert overall_why(healthy) == "No action needed"

    unknown = _result(
        overall_status=HealthStatus.UNKNOWN,
        website_status=HealthStatus.UNKNOWN,
        ssl_status=HealthStatus.UNKNOWN,
        domain_status=HealthStatus.UNKNOWN,
        dns_status=HealthStatus.UNKNOWN,
    )
    assert overall_why(unknown) == "Try again later"

    multi = _result(
        overall_status=HealthStatus.CRITICAL,
        website_status=HealthStatus.CRITICAL,
        dns_status=HealthStatus.CRITICAL,
        email_status=HealthStatus.CRITICAL,
    )
    why = overall_why(multi)
    assert why.startswith("Check ")
    assert "+1 more" in why

    warn = _result(
        overall_status=HealthStatus.WARNING,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.HEALTHY,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.CRITICAL,
    )
    assert overall_why(warn) == "No action needed"


def test_overall_summary():
    assert "Acme" in overall_summary(HealthStatus.HEALTHY, "Acme")
    assert "needs a fix" in overall_summary(HealthStatus.CRITICAL, "Acme").lower()
    assert "finish" in overall_summary(HealthStatus.UNKNOWN, "Acme").lower()


def test_settings_fields_registry():
    keys = [k for k, *_ in SETTINGS_FIELDS]
    assert len(keys) == len(set(keys))
    assert "timeout_seconds" in keys
    assert "notify_on" in keys
    assert "smtp_password" in keys
    for key, label, tip, hint in SETTINGS_FIELDS:
        assert key
        assert label
        assert tip
