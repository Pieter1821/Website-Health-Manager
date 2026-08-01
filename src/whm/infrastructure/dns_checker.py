"""DNS record resolution and snapshot helpers."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import dns.exception
import dns.resolver

from whm.domain.models import DnsRecord, Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import worst_status

logger = logging.getLogger(__name__)

RECORD_TYPES = ("A", "AAAA", "MX", "TXT", "CNAME", "NS", "SOA", "CAA")

ProgressCallback = Callable[[str], None]

# Transport / resolver failures (not "this record type is absent").
_PROBE_DNS_ERRORS = (
    dns.resolver.NoNameservers,
    dns.exception.Timeout,
    dns.resolver.LifetimeTimeout,
)


def _make_resolver(nameserver: Optional[str], timeout: float) -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver(configure=True)
    resolver.lifetime = timeout
    resolver.timeout = timeout
    if nameserver:
        resolver.nameservers = [nameserver]
    return resolver


def resolve_records(
    domain: str,
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
    record_types: tuple[str, ...] = RECORD_TYPES,
    progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """
    Resolve common DNS record types for a domain.

    Returns:
      records: list[DnsRecord]
      probe_ok: True if at least one query got a definitive DNS answer
                (including NoAnswer / NXDOMAIN), False if all queries failed
                due to timeout / resolver errors.
      nxdomain: True if the name does not exist
      errors: list of error strings from failed queries
    """
    domain = domain.strip().lower().rstrip(".")
    resolver = _make_resolver(nameserver, timeout)
    ns_label = nameserver or "system DNS"
    logger.info(
        "DNS check started for %s (resolver=%s, timeout=%ss, types=%s)",
        domain,
        ns_label,
        timeout,
        ",".join(record_types),
    )
    records: list[DnsRecord] = []
    definitive = 0
    errors: list[str] = []
    nxdomain = False

    total = len(record_types)
    for index, rtype in enumerate(record_types, start=1):
        step = f"4/8 DNS settings — checking {rtype} ({index}/{total}) for {domain}"
        if progress:
            progress(step)
        logger.info("DNS lookup %s %s …", rtype, domain)
        try:
            answers = resolver.resolve(domain, rtype)
        except dns.resolver.NXDOMAIN as exc:
            nxdomain = True
            definitive += 1
            errors.append(f"{rtype}: {exc}")
            logger.info("DNS %s %s → NXDOMAIN", rtype, domain)
            continue
        except dns.resolver.NoAnswer:
            # Resolver worked; this type simply has no records.
            definitive += 1
            logger.info("DNS %s %s → no records", rtype, domain)
            continue
        except _PROBE_DNS_ERRORS as exc:
            errors.append(f"{rtype}: {exc}")
            logger.warning("DNS %s %s → probe/network issue: %s", rtype, domain, exc)
            continue
        except dns.exception.DNSException as exc:
            if is_probe_failure(exc):
                errors.append(f"{rtype}: {exc}")
                logger.warning("DNS %s %s → probe failure: %s", rtype, domain, exc)
            else:
                definitive += 1
                errors.append(f"{rtype}: {exc}")
                logger.info("DNS %s %s → %s", rtype, domain, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            if is_probe_failure(exc):
                errors.append(f"{rtype}: {exc}")
                logger.warning("DNS %s %s → probe failure: %s", rtype, domain, exc)
            else:
                definitive += 1
                errors.append(f"{rtype}: {exc}")
                logger.info("DNS %s %s → %s", rtype, domain, exc)
            continue

        definitive += 1
        ttl = getattr(answers.rrset, "ttl", None)
        found_values: list[str] = []
        for rdata in answers:
            priority = None
            if rtype == "MX":
                priority = int(rdata.preference)
                value = str(rdata.exchange).rstrip(".")
                found_values.append(f"{priority} {value}")
            elif rtype == "TXT":
                parts = getattr(rdata, "strings", None)
                if parts:
                    value = "".join(
                        p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                        for p in parts
                    )
                else:
                    value = str(rdata).strip('"')
                found_values.append(value[:120] + ("…" if len(value) > 120 else ""))
            else:
                value = str(rdata).rstrip(".")
                found_values.append(value)
            records.append(
                DnsRecord(
                    rtype=rtype,
                    name=domain,
                    value=value,
                    ttl=int(ttl) if ttl is not None else None,
                    priority=priority,
                )
            )
        logger.info(
            "DNS %s %s → %s record(s): %s",
            rtype,
            domain,
            len(found_values),
            "; ".join(found_values) if found_values else "(empty)",
        )

    logger.info(
        "DNS check finished for %s — %s record(s), probe_ok=%s, nxdomain=%s",
        domain,
        len(records),
        definitive > 0,
        nxdomain,
    )
    return {
        "records": records,
        "probe_ok": definitive > 0,
        "nxdomain": nxdomain,
        "errors": errors,
    }


def check_dns(
    domain: str,
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
    progress: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """Resolve DNS and produce health findings for basics (A/NS presence)."""
    findings: list[Finding] = []
    try:
        result = resolve_records(
            domain,
            nameserver=nameserver,
            timeout=timeout,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("DNS check crashed for %s", domain)
        if is_probe_failure(exc):
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": [
                    probe_failed_finding(
                        "dns",
                        "DNS probe failed",
                        str(exc),
                    )
                ],
                "records": [],
                "probe_ok": False,
                "raw": {"domain": domain, "error": str(exc), "probe_failed": True},
            }
        return {
            "status": HealthStatus.CRITICAL,
            "findings": [
                Finding(
                    category="dns",
                    title="DNS lookup failed",
                    status=FindingStatus.MISSING,
                    message=str(exc),
                    recommendation="Check the domain spelling and DNS server settings.",
                )
            ],
            "records": [],
            "probe_ok": True,
            "raw": {"domain": domain, "error": str(exc)},
        }

    records: list[DnsRecord] = result["records"]
    if not result["probe_ok"]:
        detail = "; ".join(result["errors"][:3]) or "DNS resolver timed out / unreachable"
        logger.warning("DNS probe failed for %s: %s", domain, detail)
        return {
            "status": HealthStatus.UNKNOWN,
            "findings": [
                probe_failed_finding(
                    "dns",
                    "DNS probe failed",
                    detail,
                    details={"errors": result["errors"]},
                )
            ],
            "records": [],
            "probe_ok": False,
            "raw": {
                "domain": domain,
                "probe_failed": True,
                "errors": result["errors"],
            },
        }

    if result["nxdomain"] and not records:
        logger.warning("DNS NXDOMAIN for %s", domain)
        return {
            "status": HealthStatus.CRITICAL,
            "findings": [
                Finding(
                    category="dns",
                    title="Domain not found in DNS",
                    status=FindingStatus.MISSING,
                    message=f"NXDOMAIN for {domain}.",
                    recommendation="Verify the domain spelling and that it is delegated at the registrar.",
                )
            ],
            "records": [],
            "probe_ok": True,
            "raw": {"domain": domain, "nxdomain": True},
        }

    by_type: dict[str, list[DnsRecord]] = {}
    for record in records:
        by_type.setdefault(record.rtype, []).append(record)

    statuses: list[HealthStatus] = []

    if by_type.get("A") or by_type.get("AAAA"):
        addrs = [r.value for r in by_type.get("A", []) + by_type.get("AAAA", [])]
        findings.append(
            Finding(
                category="dns",
                title="Address records",
                status=FindingStatus.CORRECT,
                message="Found: " + ", ".join(addrs),
                details={
                    "a": [r.value for r in by_type.get("A", [])],
                    "aaaa": [r.value for r in by_type.get("AAAA", [])],
                },
            )
        )
        statuses.append(HealthStatus.HEALTHY)
    else:
        findings.append(
            Finding(
                category="dns",
                title="Missing A/AAAA records",
                status=FindingStatus.MISSING,
                message="No IPv4/IPv6 address records found for the apex domain.",
                recommendation="Add an A (or AAAA) record pointing to the web server / CDN.",
            )
        )
        statuses.append(HealthStatus.CRITICAL)

    if by_type.get("NS"):
        findings.append(
            Finding(
                category="dns",
                title="Name servers",
                status=FindingStatus.CORRECT,
                message=", ".join(r.value for r in by_type["NS"]),
            )
        )
    else:
        findings.append(
            Finding(
                category="dns",
                title="Missing NS records",
                status=FindingStatus.INCORRECT,
                message="No NS records returned for this query.",
                recommendation="Verify the domain is delegated correctly at the registrar.",
            )
        )
        statuses.append(HealthStatus.WARNING)

    for rtype in ("MX", "TXT", "CNAME", "SOA", "CAA"):
        if rtype in by_type:
            findings.append(
                Finding(
                    category="dns",
                    title=f"{rtype} records",
                    status=FindingStatus.INFO,
                    message="; ".join(
                        (f"{r.priority} {r.value}" if r.priority is not None else r.value)
                        for r in by_type[rtype]
                    ),
                )
            )

    status = worst_status(statuses) if statuses else HealthStatus.UNKNOWN
    logger.info(
        "DNS settings result for %s: status=%s counts=%s",
        domain,
        status.value,
        {k: len(v) for k, v in by_type.items()},
    )
    return {
        "status": status,
        "findings": findings,
        "records": records,
        "probe_ok": True,
        "raw": {
            "domain": domain,
            "counts": {k: len(v) for k, v in by_type.items()},
        },
    }


def diff_dns_records(
    old: list[DnsRecord], new: list[DnsRecord]
) -> list[dict[str, str]]:
    """
    Compare two DNS snapshots.

    Returns a list of change dicts: {change, rtype, name, old_value, new_value}.
    """

    def key(r: DnsRecord) -> tuple[str, str, str, Optional[int]]:
        return (r.rtype, r.name.lower(), r.value.lower(), r.priority)

    old_map = {key(r): r for r in old}
    new_map = {key(r): r for r in new}
    changes: list[dict[str, str]] = []

    for k, record in new_map.items():
        if k not in old_map:
            changes.append(
                {
                    "change": "added",
                    "rtype": record.rtype,
                    "name": record.name,
                    "old_value": "",
                    "new_value": record.value,
                }
            )
    for k, record in old_map.items():
        if k not in new_map:
            changes.append(
                {
                    "change": "removed",
                    "rtype": record.rtype,
                    "name": record.name,
                    "old_value": record.value,
                    "new_value": "",
                }
            )
    return changes
