"""
Guard against false “Needs a fix” results from local probe noise.

Network/Wi‑Fi/DNS probe failures must stay UNKNOWN / inconclusive.
Real customer issues (expired cert text, NXDOMAIN, missing SPF) must still surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from whm.application.services import extract_domain
from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import (
    aggregate_status,
    days_to_status,
    finding_to_status,
    worst_known_status,
)
from whm.infrastructure.dns_checker import check_dns
from whm.infrastructure.email_checker import check_email, parse_spf
from whm.infrastructure.http_checker import check_website, normalize_url
from whm.infrastructure.ssl_checker import check_ssl
from whm.infrastructure.whois_checker import check_domain
from whm.presentation.webapi import serialize_detail, serialize_site_row
from whm.domain.models import HealthCheckResult, RiskLevel, Website


# --- Probe classification -------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "getaddrinfo failed",
        "[Errno 11001] getaddrinfo failed",
        "Connection failed: All connection attempts failed",
        "All connection attempts failed",
        "Failed to resolve 'example.com'",
        "The resolution lifetime expired after 5.1 seconds",
        "timed out",
        "DNS operation timed out",
        "Name or service not known",
        "nodename nor servname provided, or not known",
        "Network is unreachable",
        "WinError 10060",
    ],
)
def test_probe_patterns_catch_local_failures(message: str):
    assert is_probe_failure(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "HTTP 503 Service Unavailable",
        "certificate has expired",
        "certificate verify failed",
        "NXDOMAIN",
        "SPF record missing",
    ],
)
def test_probe_patterns_do_not_hide_real_site_errors(message: str):
    assert is_probe_failure(message) is False


# --- HTTP -----------------------------------------------------------------


def test_http_timeout_is_unknown_not_critical():
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.side_effect = httpx.TimeoutException("timeout")
        result = check_website("https://example.com", timeout=1)
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["raw"].get("probe_failed") is True
    assert result["findings"][0].status == FindingStatus.INCONCLUSIVE


def test_http_connect_error_is_unknown_not_critical():
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.side_effect = httpx.ConnectError("All connection attempts failed")
        result = check_website("https://example.com", timeout=1)
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["findings"][0].status == FindingStatus.INCONCLUSIVE
    assert "Critical" not in result["findings"][0].title


def test_http_503_is_real_problem():
    response = MagicMock()
    response.status_code = 503
    response.is_redirect = False
    response.url = "https://example.com/"
    response.headers = {}
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.return_value = response
        result = check_website("https://example.com", timeout=1)
    assert result["status"] == HealthStatus.CRITICAL
    assert result["findings"][0].status == FindingStatus.INCORRECT


def test_http_403_is_not_a_problem():
    response = MagicMock()
    response.status_code = 403
    response.is_redirect = False
    response.url = "https://example.com/"
    response.headers = {}
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.return_value = response
        result = check_website("https://example.com", timeout=1)
    assert result["status"] == HealthStatus.HEALTHY
    assert all(f.status != FindingStatus.INCORRECT for f in result["findings"])


def test_http_200_is_healthy():
    response = MagicMock()
    response.status_code = 200
    response.is_redirect = False
    response.url = "https://example.com/"
    response.headers = {}
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.return_value = response
        result = check_website("https://example.com", timeout=1)
    assert result["status"] == HealthStatus.HEALTHY


# --- SSL ------------------------------------------------------------------


def test_ssl_timeout_is_unknown():
    with patch(
        "whm.infrastructure.ssl_checker.socket.create_connection",
        side_effect=TimeoutError("timed out"),
    ):
        result = check_ssl("example.com", timeout=1)
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["raw"].get("probe_failed") is True


def test_ssl_getaddrinfo_is_unknown():
    with patch(
        "whm.infrastructure.ssl_checker.socket.create_connection",
        side_effect=OSError("[Errno 11001] getaddrinfo failed"),
    ):
        result = check_ssl("example.com", timeout=1)
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["findings"][0].status == FindingStatus.INCONCLUSIVE


def test_ssl_cert_verify_failure_is_critical():
    import ssl

    with patch(
        "whm.infrastructure.ssl_checker.socket.create_connection",
        side_effect=ssl.SSLCertVerificationError("certificate has expired"),
    ):
        result = check_ssl("example.com", timeout=1)
    assert result["status"] == HealthStatus.CRITICAL


# --- WHOIS ----------------------------------------------------------------


def test_whois_exception_is_unknown_not_critical():
    with patch("whm.infrastructure.whois_checker._whois_lookup", side_effect=Exception("getaddrinfo failed")):
        result = check_domain("example.com")
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["findings"][0].status == FindingStatus.INFO


def test_whois_empty_object_is_unknown():
    empty = MagicMock()
    empty.domain_name = None
    empty.expiration_date = None
    empty.registrar = None
    with patch("whm.infrastructure.whois_checker._whois_lookup", return_value=empty):
        result = check_domain("example.com")
    assert result["status"] == HealthStatus.UNKNOWN


def test_whois_expiry_soon_is_warning_or_critical():
    data = MagicMock()
    data.domain_name = "example.com"
    data.expiration_date = datetime.now(timezone.utc) + timedelta(days=20)
    data.creation_date = None
    data.updated_date = None
    data.registrar = "Example Registrar"
    data.status = None
    with patch("whm.infrastructure.whois_checker._whois_lookup", return_value=data):
        result = check_domain("example.com")
    assert result["status"] == HealthStatus.WARNING


# --- DNS ------------------------------------------------------------------


def test_dns_probe_failure_unknown_and_not_settings_change():
    with patch(
        "whm.infrastructure.dns_checker.resolve_records",
        return_value={
            "records": [],
            "probe_ok": False,
            "nxdomain": False,
            "errors": ["DNS operation timed out"],
            "raw": {},
        },
    ):
        result = check_dns("example.com")
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["probe_ok"] is False
    assert result["findings"][0].status == FindingStatus.INCONCLUSIVE


def test_dns_nxdomain_is_real_critical():
    with patch(
        "whm.infrastructure.dns_checker.resolve_records",
        return_value={
            "records": [],
            "probe_ok": True,
            "nxdomain": True,
            "errors": [],
            "raw": {},
        },
    ):
        result = check_dns("no-such-domain-xyz.invalid")
    assert result["status"] == HealthStatus.CRITICAL


# --- Email ----------------------------------------------------------------


def test_email_dns_probe_failure_does_not_claim_spf_missing():
    with patch(
        "whm.infrastructure.email_checker._txt_lookup",
        return_value={"probe_ok": False, "records": [], "error": "timeout"},
    ):
        result = check_email("example.com", probe_smtp=False)
    assert result["status"] == HealthStatus.UNKNOWN
    titles = " ".join(f.title.lower() for f in result["findings"])
    assert "inconclusive" in titles
    assert "missing" not in titles


def test_spf_really_missing_is_reported():
    parsed = parse_spf([])
    assert any(f.status == FindingStatus.MISSING for f in parsed["findings"])


# --- Aggregation / overall ------------------------------------------------


def test_all_unknown_checks_do_not_become_critical():
    assert (
        worst_known_status(
            [
                HealthStatus.UNKNOWN,
                HealthStatus.UNKNOWN,
                HealthStatus.UNKNOWN,
            ]
        )
        == HealthStatus.UNKNOWN
    )


def test_mixed_unknown_and_healthy_stays_healthy():
    assert (
        worst_known_status([HealthStatus.UNKNOWN, HealthStatus.HEALTHY])
        == HealthStatus.HEALTHY
    )


def test_aggregate_probe_noise_alone_is_unknown():
    findings = [
        probe_failed_finding("website", "web", "All connection attempts failed"),
        probe_failed_finding("dns", "dns", "timeout"),
        Finding("ssl", "issuer", FindingStatus.INFO, "Let's Encrypt"),
    ]
    # INFO maps healthy; with only INFO + inconclusive → healthy from INFO
    # Ensure inconclusive alone is unknown:
    only_probe = [
        probe_failed_finding("website", "web", "timeout"),
        probe_failed_finding("dns", "dns", "timeout"),
    ]
    assert aggregate_status(only_probe) == HealthStatus.UNKNOWN


def test_spf_missing_is_warning_not_critical():
    """Mail often still works without SPF — do not scare staff with red."""
    findings = [
        probe_failed_finding("website", "web", "timeout"),
        Finding("spf", "SPF missing", FindingStatus.MISSING, "none"),
    ]
    assert aggregate_status(findings) == HealthStatus.WARNING


def test_mx_missing_is_still_critical():
    findings = [Finding("mx", "MX missing", FindingStatus.MISSING, "none")]
    assert aggregate_status(findings) == HealthStatus.CRITICAL


def test_days_to_status_boundaries_no_false_critical():
    assert days_to_status(31) == HealthStatus.HEALTHY
    assert days_to_status(30) == HealthStatus.WARNING
    assert days_to_status(15) == HealthStatus.WARNING
    assert days_to_status(14) == HealthStatus.WARNING
    assert days_to_status(13) == HealthStatus.CRITICAL
    assert days_to_status(None) == HealthStatus.UNKNOWN


# --- URL / import false identity -----------------------------------------


def test_https_url_does_not_become_literal_https_domain():
    assert extract_domain("https://www.example.com/path") == "www.example.com"
    with pytest.raises(ValueError):
        extract_domain("https://")
    with pytest.raises(ValueError):
        normalize_url("not a domain")


# --- UI serialization must not invent problems ---------------------------


def test_serialize_hides_security_and_email_noise():
    site = Website(
        id=1,
        url="https://example.com",
        domain="example.com",
        display_name="Example",
    )
    result = HealthCheckResult(
        website_id=1,
        overall_status=HealthStatus.CRITICAL,
        risk_level=RiskLevel.HIGH,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.WARNING,
        domain_status=HealthStatus.UNKNOWN,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.CRITICAL,
        findings=[
            Finding("security", "HSTS missing", FindingStatus.MISSING, "no hsts"),
            Finding(
                "spf",
                "SPF missing",
                FindingStatus.MISSING,
                "none",
                "Add SPF",
            ),
            Finding("ssl", "Hostname match", FindingStatus.CORRECT, "ok"),
            Finding(
                "ssl",
                "Certificate expiring soon",
                FindingStatus.INCORRECT,
                "30 days",
                "Renew",
            ),
        ],
        raw={
            "ssl": {
                "not_after": "2026-12-01T00:00:00+00:00",
                "days_remaining": 120,
            },
            "whois": {"expiration_date": None, "days_remaining": None},
        },
    )
    detail = serialize_detail(site, result, [result], [])
    assert "HSTS" not in detail["findings_html"]
    assert "SPF missing" not in detail["findings_html"]
    assert "Hostname match" not in detail["findings_html"]  # OK rows hidden
    assert "Certificate expiring soon" in detail["findings_html"]
    row = serialize_site_row(site, result)
    assert row["ssl_expires"] == "2026-12-01"
    assert row["domain_expires"] == "—"
    assert row["overall_label"] == "Worth a look"  # email critical ignored


def test_inconclusive_finding_never_maps_to_critical():
    finding = probe_failed_finding(
        "website",
        "Website check inconclusive",
        "Connection failed: All connection attempts failed",
    )
    assert finding_to_status(finding) == HealthStatus.UNKNOWN
