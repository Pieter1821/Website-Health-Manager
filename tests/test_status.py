"""Tests for domain status aggregation rules."""

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.status import aggregate_status, days_to_status, status_to_risk, worst_status


def test_days_to_status_ladder():
    assert days_to_status(None) == HealthStatus.UNKNOWN
    assert days_to_status(120) == HealthStatus.HEALTHY
    assert days_to_status(31) == HealthStatus.HEALTHY
    assert days_to_status(30) == HealthStatus.WARNING
    assert days_to_status(14) == HealthStatus.WARNING
    assert days_to_status(13) == HealthStatus.CRITICAL
    assert days_to_status(8) == HealthStatus.CRITICAL
    assert days_to_status(-1) == HealthStatus.CRITICAL


def test_aggregate_status_prefers_critical():
    findings = [
        Finding("spf", "ok", FindingStatus.CORRECT, "ok"),
        Finding("mx", "missing", FindingStatus.MISSING, "gone"),
    ]
    assert aggregate_status(findings) == HealthStatus.CRITICAL


def test_worst_status():
    assert worst_status([HealthStatus.HEALTHY, HealthStatus.WARNING]) == HealthStatus.WARNING


def test_status_to_risk():
    assert status_to_risk(HealthStatus.CRITICAL).value == "high"
