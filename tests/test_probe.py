"""Probe-failure classification must not produce false Critical results."""

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import aggregate_status, finding_to_status, worst_known_status


def test_is_probe_failure_detects_common_wifi_errors():
    assert is_probe_failure("getaddrinfo failed")
    assert is_probe_failure("The resolution lifetime expired after 10.1 seconds")
    assert is_probe_failure("timed out")
    assert is_probe_failure("[Errno 11001] getaddrinfo failed")
    assert not is_probe_failure("HTTP 503 Service Unavailable")
    assert not is_probe_failure("certificate has expired")


def test_inconclusive_finding_maps_to_unknown():
    finding = probe_failed_finding("website", "check inconclusive", "timed out")
    assert finding.status == FindingStatus.INCONCLUSIVE
    assert finding_to_status(finding) == HealthStatus.UNKNOWN


def test_aggregate_ignores_inconclusive_when_real_issues_exist():
    findings = [
        probe_failed_finding("dns", "dns probe failed", "timeout"),
        Finding("spf", "SPF missing", FindingStatus.MISSING, "none"),
    ]
    # SPF gaps are amber (mail often still works); probe noise is ignored.
    assert aggregate_status(findings) == HealthStatus.WARNING

    mx_findings = [
        probe_failed_finding("dns", "dns probe failed", "timeout"),
        Finding("mx", "MX missing", FindingStatus.MISSING, "none"),
    ]
    assert aggregate_status(mx_findings) == HealthStatus.CRITICAL


def test_aggregate_all_inconclusive_is_unknown():
    findings = [
        probe_failed_finding("website", "web", "timeout"),
        probe_failed_finding("ssl", "ssl", "timeout"),
    ]
    assert aggregate_status(findings) == HealthStatus.UNKNOWN


def test_worst_known_status_skips_unknown():
    assert (
        worst_known_status(
            [HealthStatus.UNKNOWN, HealthStatus.WARNING, HealthStatus.UNKNOWN]
        )
        == HealthStatus.WARNING
    )
    assert (
        worst_known_status([HealthStatus.UNKNOWN, HealthStatus.UNKNOWN])
        == HealthStatus.UNKNOWN
    )
