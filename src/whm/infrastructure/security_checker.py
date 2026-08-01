"""Security header and basic TLS posture checks (Phase 3)."""

from __future__ import annotations

from typing import Any

import httpx

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import worst_status
from whm.infrastructure.http_checker import normalize_url

IMPORTANT_HEADERS = {
    "strict-transport-security": ("HSTS", True),
    "content-security-policy": ("Content Security Policy", False),
    "x-frame-options": ("Clickjacking protection (X-Frame-Options)", False),
    "x-content-type-options": ("X-Content-Type-Options", False),
    "referrer-policy": ("Referrer Policy", False),
    "permissions-policy": ("Permissions Policy", False),
}


def check_security_headers(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch response headers and report missing security headers in plain terms."""
    target = normalize_url(url)
    findings: list[Finding] = []
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=True) as client:
            response = client.get(target)
        headers = {k.lower(): v for k, v in response.headers.items()}
    except Exception as exc:  # noqa: BLE001
        if is_probe_failure(exc):
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": [
                    probe_failed_finding(
                        "security",
                        "Security check inconclusive",
                        str(exc),
                    )
                ],
                "raw": {"probe_failed": True, "error": str(exc)},
            }
        return {
            "status": HealthStatus.WARNING,
            "findings": [
                Finding(
                    category="security",
                    title="Could not read security headers",
                    status=FindingStatus.INCORRECT,
                    message=str(exc),
                    recommendation="Confirm the website is online, then try again.",
                )
            ],
            "raw": {"error": str(exc)},
        }

    statuses: list[HealthStatus] = [HealthStatus.HEALTHY]
    for key, (label, critical_if_missing) in IMPORTANT_HEADERS.items():
        value = headers.get(key)
        if value:
            findings.append(
                Finding(
                    category="security",
                    title=label,
                    status=FindingStatus.CORRECT,
                    message=value[:180],
                )
            )
        else:
            findings.append(
                Finding(
                    category="security",
                    title=f"{label} missing",
                    status=FindingStatus.MISSING if critical_if_missing else FindingStatus.INCORRECT,
                    message=f"The website did not send the {label} header.",
                    recommendation="Turn on this security setting in hosting or the CDN.",
                )
            )
            statuses.append(
                HealthStatus.WARNING if not critical_if_missing else HealthStatus.WARNING
            )

    return {
        "status": worst_status(statuses),
        "findings": findings,
        "raw": {"headers": {k: headers.get(k) for k in IMPORTANT_HEADERS}},
    }
