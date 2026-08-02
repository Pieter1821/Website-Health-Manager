"""Domain WHOIS / expiry checks (always on registrable domain, never subdomain)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from whois.parser import WhoisEntry
from whois.whois import NICClient

from whm.domain.hostnames import normalize_hostname, registrable_domain
from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.status import days_to_status

logger = logging.getLogger(__name__)

# ccTLDs where RDAP/WHOIS is often incomplete — prefer unknown over guesses.
_FRAGILE_SUFFIXES = frozenset(
    {
        "co.za",
        "org.za",
        "net.za",
        "web.za",
        "gov.za",
        "ac.za",
        "edu.za",
        "za",
    }
)


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


def _suffix_of(domain: str) -> str:
    labels = domain.split(".")
    if len(labels) >= 2 and ".".join(labels[-2:]) in _FRAGILE_SUFFIXES:
        return ".".join(labels[-2:])
    return labels[-1] if labels else domain


def _unavailable(domain: str, queried: str, reason: str) -> dict[str, Any]:
    fragile = _suffix_of(queried) in _FRAGILE_SUFFIXES
    message = f"Could not retrieve reliable expiry for {queried}: {reason}"
    if fragile:
        message += (
            f" (.{_suffix_of(queried)} WHOIS/RDAP is often incomplete — "
            "WHM will not guess an expiry date.)"
        )
    return {
        "status": HealthStatus.UNKNOWN,
        "findings": [
            Finding(
                category="domain",
                title="Domain expiry unknown",
                status=FindingStatus.INFO,
                message=message,
                recommendation=(
                    "Confirm the renewal date in the registrar portal "
                    "(e.g. the ZA Central Registry / your .co.za registrar)."
                ),
                details={"input_host": domain, "queried_domain": queried},
            )
        ],
        "raw": {
            "domain": domain,
            "queried_domain": queried,
            "error": reason,
            "days_remaining": None,
            "expiration_date": None,
        },
    }


def _whois_lookup(queried: str, timeout: int = 10) -> Any:
    """
    Query WHOIS for an already-normalized registrable domain.

    Avoids python-whois extract_domain(), which needs public_suffix_list.dat —
    that file is often missing from frozen Windows builds and breaks Domain expires.
    """
    nic_client = NICClient()
    text = nic_client.whois_lookup(
        None,
        queried,
        0,
        quiet=True,
        ignore_socket_errors=True,
        timeout=timeout,
    )
    if not text:
        raise RuntimeError("WHOIS returned no output")
    return WhoisEntry.load(queried, text)


def check_domain(domain: str) -> dict[str, Any]:
    """Look up WHOIS on the registrable domain and evaluate expiry."""
    input_host = normalize_hostname(domain)
    queried = registrable_domain(input_host) or input_host
    findings: list[Finding] = []

    if input_host and queried != input_host:
        findings.append(
            Finding(
                category="domain",
                title="Checked registered domain",
                status=FindingStatus.INFO,
                message=(
                    f"{input_host} is a hostname/subdomain — "
                    f"expiry is checked for {queried}."
                ),
                details={"input_host": input_host, "queried_domain": queried},
            )
        )

    try:
        data = _whois_lookup(queried)
    except Exception as exc:  # noqa: BLE001 — WHOIS is flaky / often blocked
        logger.info("WHOIS lookup failed for %s (from %s): %s", queried, input_host, exc)
        return _unavailable(input_host, queried, str(exc))

    if data is None or (
        not getattr(data, "domain_name", None)
        and not (isinstance(data, dict) and data.get("domain_name"))
        and not getattr(data, "expiration_date", None)
        and not (isinstance(data, dict) and data.get("expiration_date"))
        and not getattr(data, "registrar", None)
        and not (isinstance(data, dict) and data.get("registrar"))
    ):
        logger.info("WHOIS returned empty data for %s", queried)
        return _unavailable(input_host, queried, "empty response (DNS or registry unreachable)")

    def _get(name: str) -> Any:
        if isinstance(data, dict):
            return data.get(name)
        return getattr(data, name, None)

    expiry = _as_datetime(_get("expiration_date"))
    created = _as_datetime(_get("creation_date"))
    updated = _as_datetime(_get("updated_date"))
    registrar = _get("registrar")
    status_field = _get("status")
    if isinstance(status_field, list):
        status_field = ", ".join(str(s) for s in status_field)

    if expiry is None:
        findings.append(
            Finding(
                category="domain",
                title="Domain expiry unknown",
                status=FindingStatus.INFO,
                message=(
                    f"WHOIS for {queried} did not return an expiration date. "
                    "WHM will not invent one."
                ),
                recommendation="Confirm expiry in the registrar control panel.",
                details={"registrar": registrar, "queried_domain": queried},
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
                message=(
                    f"{queried} expires {expiry.date().isoformat()} "
                    f"({days_remaining} days remaining)."
                ),
                recommendation="Enable auto-renew and renew early if within 30 days.",
                details={
                    "days_remaining": days_remaining,
                    "expiration_date": expiry.isoformat(),
                    "queried_domain": queried,
                },
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
            "domain": input_host,
            "queried_domain": queried,
            "registrar": registrar,
            "expiration_date": expiry.isoformat() if expiry else None,
            "creation_date": created.isoformat() if created else None,
            "updated_date": updated.isoformat() if updated else None,
            "status": status_field,
            "days_remaining": days_remaining if expiry else None,
        },
    }
