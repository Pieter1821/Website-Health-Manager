"""Domain WHOIS / expiry checks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import whois

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.status import days_to_status

logger = logging.getLogger(__name__)


def _as_datetime(value: Any) -> Optional[datetime]:
    """Normalize python-whois date fields (may be list or naive datetime)."""
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _unavailable(domain: str, reason: str) -> dict[str, Any]:
    return {
        "status": HealthStatus.UNKNOWN,
        "findings": [
            Finding(
                category="domain",
                title="WHOIS unavailable",
                status=FindingStatus.INFO,
                message=f"Could not retrieve WHOIS for {domain}: {reason}",
                recommendation=(
                    "WHOIS needs DNS to reach the registry. Check your network/DNS, "
                    "or confirm expiry in the registrar portal."
                ),
            )
        ],
        "raw": {"domain": domain, "error": reason},
    }


def check_domain(domain: str) -> dict[str, Any]:
    """Look up WHOIS data and evaluate domain expiry."""
    domain = domain.strip().lower().rstrip(".")
    findings: list[Finding] = []

    try:
        data = whois.whois(domain)
    except Exception as exc:  # noqa: BLE001 — WHOIS is flaky / often blocked
        logger.info("WHOIS lookup failed for %s: %s", domain, exc)
        return _unavailable(domain, str(exc))

    # python-whois sometimes returns an empty object after a DNS/socket failure
    # instead of raising (it only logs the error).
    if data is None or (
        not getattr(data, "domain_name", None)
        and not getattr(data, "expiration_date", None)
        and not getattr(data, "registrar", None)
    ):
        logger.info("WHOIS returned empty data for %s (often DNS failure)", domain)
        return _unavailable(domain, "empty response (DNS or registry unreachable)")

    expiry = _as_datetime(getattr(data, "expiration_date", None))
    created = _as_datetime(getattr(data, "creation_date", None))
    updated = _as_datetime(getattr(data, "updated_date", None))
    registrar = getattr(data, "registrar", None)
    status_field = getattr(data, "status", None)
    if isinstance(status_field, list):
        status_field = ", ".join(str(s) for s in status_field)

    if expiry is None:
        findings.append(
            Finding(
                category="domain",
                title="Domain expiry unknown",
                status=FindingStatus.INFO,
                message="WHOIS did not return an expiration date (common for some TLDs/privacy).",
                recommendation="Confirm expiry in the registrar control panel.",
                details={"registrar": registrar},
            )
        )
        status = HealthStatus.UNKNOWN
        days_remaining = None
    else:
        days_remaining = (expiry - datetime.now(timezone.utc)).days
        status = days_to_status(days_remaining)
        findings.append(
            Finding(
                category="domain",
                title="Domain expiry",
                status=(
                    FindingStatus.CORRECT
                    if days_remaining > 30
                    else FindingStatus.INCORRECT
                    if days_remaining >= 0
                    else FindingStatus.MISSING
                ),
                message=f"Expires {expiry.date().isoformat()} ({days_remaining} days remaining).",
                recommendation="Enable auto-renew and renew early if within 30 days.",
                details={"days_remaining": days_remaining, "expiration_date": expiry.isoformat()},
            )
        )

    if registrar:
        findings.append(
            Finding(
                category="domain",
                title="Registrar",
                status=FindingStatus.INFO,
                message=str(registrar),
            )
        )

    return {
        "status": status,
        "findings": findings,
        "raw": {
            "domain": domain,
            "registrar": registrar,
            "expiration_date": expiry.isoformat() if expiry else None,
            "creation_date": created.isoformat() if created else None,
            "updated_date": updated.isoformat() if updated else None,
            "status": status_field,
            "days_remaining": days_remaining if expiry else None,
        },
    }
