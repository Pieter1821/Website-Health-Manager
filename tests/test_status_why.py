"""Plain-language explanations for status colours."""

from whm.domain.models import HealthCheckResult, HealthStatus, RiskLevel
from whm.domain.status import site_facing_status
from whm.presentation.copy import overall_why


def _result(**statuses: HealthStatus) -> HealthCheckResult:
    return HealthCheckResult(
        website_id=1,
        overall_status=statuses.get("overall", HealthStatus.WARNING),
        risk_level=RiskLevel.MEDIUM,
        website_status=statuses.get("website", HealthStatus.HEALTHY),
        ssl_status=statuses.get("ssl", HealthStatus.HEALTHY),
        domain_status=statuses.get("domain", HealthStatus.HEALTHY),
        dns_status=statuses.get("dns", HealthStatus.HEALTHY),
        email_status=statuses.get("email", HealthStatus.WARNING),
    )


def test_email_does_not_drive_overall_or_why():
    why = overall_why(
        _result(
            overall=HealthStatus.CRITICAL,
            email=HealthStatus.CRITICAL,
            website=HealthStatus.HEALTHY,
            ssl=HealthStatus.HEALTHY,
            domain=HealthStatus.HEALTHY,
            dns=HealthStatus.HEALTHY,
        )
    )
    assert why == "No action needed"
    assert (
        site_facing_status(
            HealthStatus.HEALTHY,
            HealthStatus.HEALTHY,
            HealthStatus.HEALTHY,
            HealthStatus.HEALTHY,
        )
        == HealthStatus.HEALTHY
    )


def test_amber_points_at_dns():
    why = overall_why(_result(overall=HealthStatus.WARNING, dns=HealthStatus.WARNING))
    assert why == "Check DNS"


def test_red_points_at_website():
    why = overall_why(
        _result(
            overall=HealthStatus.CRITICAL,
            website=HealthStatus.CRITICAL,
            email=HealthStatus.HEALTHY,
        )
    )
    assert why == "Check Website"


def test_healthy_is_simple():
    why = overall_why(
        _result(overall=HealthStatus.HEALTHY, email=HealthStatus.HEALTHY)
    )
    assert why == "No action needed"
