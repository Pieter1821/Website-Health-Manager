"""Email authentication (SPF/DKIM/DMARC/MX/SMTP) and SendGrid DNS checks."""

from __future__ import annotations

import re
import socket
from typing import Any, Optional

import dns.exception
import dns.resolver

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import aggregate_status
from whm.infrastructure.dns_checker import resolve_records

# Rough SPF mechanism tokens that cause DNS lookups.
_SPF_LOOKUP_MECHS = re.compile(
    r"\b(?:include|a|mx|ptr|exists|redirect)=?",
    re.IGNORECASE,
)


def _resolver(nameserver: Optional[str], timeout: float) -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver(configure=True)
    resolver.lifetime = timeout
    resolver.timeout = timeout
    if nameserver:
        resolver.nameservers = [nameserver]
    return resolver


def _txt_lookup(
    name: str, nameserver: Optional[str], timeout: float
) -> dict[str, Any]:
    """
    Lookup TXT records.

    Returns {"probe_ok": bool, "records": list[str], "error": str|None}.
    Empty records with probe_ok=True means DNS answered and there is no TXT.
    """
    resolver = _resolver(nameserver, timeout)
    try:
        answers = resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.YXDOMAIN):
        return {"probe_ok": True, "records": [], "error": None}
    except (dns.exception.Timeout, dns.resolver.LifetimeTimeout, dns.resolver.NoNameservers) as exc:
        return {"probe_ok": False, "records": [], "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        if is_probe_failure(exc):
            return {"probe_ok": False, "records": [], "error": str(exc)}
        return {"probe_ok": True, "records": [], "error": str(exc)}

    values: list[str] = []
    for rdata in answers:
        parts = getattr(rdata, "strings", None)
        if parts:
            values.append(
                "".join(
                    p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                    for p in parts
                )
            )
        else:
            values.append(str(rdata).strip('"'))
    return {"probe_ok": True, "records": values, "error": None}


def _txt_records(name: str, nameserver: Optional[str], timeout: float) -> list[str]:
    """Backward-compatible helper used by tests / simple callers."""
    return list(_txt_lookup(name, nameserver, timeout)["records"])


def parse_spf(txt_records: list[str]) -> dict[str, Any]:
    """Analyze SPF TXT records for common problems."""
    spf_records = [t for t in txt_records if t.lower().startswith("v=spf1")]
    findings: list[Finding] = []

    if not spf_records:
        findings.append(
            Finding(
                category="spf",
                title="SPF record",
                status=FindingStatus.MISSING,
                message="No SPF TXT record (v=spf1) found on the domain.",
                recommendation="Add a single TXT record starting with v=spf1 that lists allowed senders.",
            )
        )
        return {"findings": findings, "records": [], "lookup_count": 0}

    if len(spf_records) > 1:
        findings.append(
            Finding(
                category="spf",
                title="Duplicate SPF",
                status=FindingStatus.INCORRECT,
                message=f"Found {len(spf_records)} SPF records; only one is allowed.",
                recommendation="Merge into a single SPF TXT record.",
                details={"records": spf_records},
            )
        )
    else:
        findings.append(
            Finding(
                category="spf",
                title="SPF record exists",
                status=FindingStatus.CORRECT,
                message=spf_records[0],
            )
        )

    record = spf_records[0]
    # Count DNS-causing mechanisms (RFC 7208 soft limit of 10).
    lookup_count = len(_SPF_LOOKUP_MECHS.findall(record))
    if lookup_count > 10:
        findings.append(
            Finding(
                category="spf",
                title="SPF lookup limit exceeded",
                status=FindingStatus.INCORRECT,
                message=f"Estimated {lookup_count} DNS lookups (limit is 10).",
                recommendation="Flatten SPF or remove unused includes.",
            )
        )
    else:
        findings.append(
            Finding(
                category="spf",
                title="SPF lookup count",
                status=FindingStatus.CORRECT,
                message=f"Estimated {lookup_count} DNS lookups (limit 10).",
            )
        )

    if not re.search(r"\s(?:[~+\-?]?)all\b", record, re.IGNORECASE):
        findings.append(
            Finding(
                category="spf",
                title="SPF missing all mechanism",
                status=FindingStatus.INCORRECT,
                message="SPF record has no terminal 'all' mechanism.",
                recommendation="End SPF with ~all (softfail) or -all (fail).",
            )
        )

    return {"findings": findings, "records": spf_records, "lookup_count": lookup_count}


def check_dkim(
    domain: str,
    selectors: list[str],
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Check DKIM public keys for each selector."""
    findings: list[Finding] = []
    found: list[str] = []
    probe_failures = 0
    attempts = 0

    for selector in selectors:
        selector = selector.strip()
        if not selector:
            continue
        name = f"{selector}._domainkey.{domain}"
        lookup = _txt_lookup(name, nameserver, timeout)
        attempts += 1
        if not lookup["probe_ok"]:
            probe_failures += 1
            findings.append(
                probe_failed_finding(
                    "dkim",
                    f"DKIM selector '{selector}' check inconclusive",
                    lookup["error"] or "DNS probe failed",
                )
            )
            continue
        txts = lookup["records"]
        dkim = [t for t in txts if "p=" in t.lower() or t.lower().startswith("v=dkim1")]
        if dkim:
            has_key = any(
                re.search(r"(?i)\bp=([A-Za-z0-9+/=]+)", t) and "p=;" not in t.replace(" ", "")
                for t in dkim
            )
            if has_key:
                found.append(selector)
                findings.append(
                    Finding(
                        category="dkim",
                        title=f"DKIM selector '{selector}'",
                        status=FindingStatus.CORRECT,
                        message=f"Public key present at {name}.",
                        details={"record": dkim[0][:200]},
                    )
                )
            else:
                findings.append(
                    Finding(
                        category="dkim",
                        title=f"DKIM selector '{selector}' empty key",
                        status=FindingStatus.INCORRECT,
                        message=f"Record at {name} has empty/revoked p=.",
                        recommendation="Publish a valid DKIM public key for this selector.",
                    )
                )
        else:
            findings.append(
                Finding(
                    category="dkim",
                    title=f"DKIM selector '{selector}'",
                    status=FindingStatus.MISSING,
                    message=f"No DKIM TXT at {name}.",
                    recommendation="Add the DKIM CNAME/TXT provided by your ESP (e.g. SendGrid).",
                )
            )

    if found:
        # Downgrade pure-missing noise: if at least one selector works, treat missing others as info.
        adjusted: list[Finding] = []
        for f in findings:
            if f.status == FindingStatus.MISSING and f.category == "dkim":
                adjusted.append(
                    Finding(
                        category=f.category,
                        title=f.title,
                        status=FindingStatus.INFO,
                        message=f.message + " (optional if another selector is active)",
                        recommendation=f.recommendation,
                        details=f.details,
                    )
                )
            else:
                adjusted.append(f)
        findings = adjusted

    return {
        "findings": findings,
        "found_selectors": found,
        "probe_ok": attempts == 0 or probe_failures < attempts,
    }


def check_dmarc(
    domain: str,
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Validate _dmarc TXT policy."""
    findings: list[Finding] = []
    name = f"_dmarc.{domain}"
    lookup = _txt_lookup(name, nameserver, timeout)
    if not lookup["probe_ok"]:
        return {
            "findings": [
                probe_failed_finding(
                    "dmarc",
                    "DMARC check inconclusive",
                    lookup["error"] or "DNS probe failed",
                )
            ],
            "record": None,
            "probe_ok": False,
        }
    txts = lookup["records"]
    dmarc_records = [t for t in txts if t.lower().startswith("v=dmarc1")]

    if not dmarc_records:
        findings.append(
            Finding(
                category="dmarc",
                title="DMARC record",
                status=FindingStatus.MISSING,
                message=f"No DMARC TXT at {name}.",
                recommendation="Add TXT v=DMARC1; p=none; rua=mailto:you@example.com then tighten policy.",
            )
        )
        return {"findings": findings, "record": None, "probe_ok": True}

    record = dmarc_records[0]
    policy_match = re.search(r"(?i)\bp=(none|quarantine|reject)\b", record)
    rua = re.search(r"(?i)\brua=([^;]+)", record)
    ruf = re.search(r"(?i)\bruf=([^;]+)", record)
    pct = re.search(r"(?i)\bpct=(\d+)", record)

    findings.append(
        Finding(
            category="dmarc",
            title="DMARC record exists",
            status=FindingStatus.CORRECT,
            message=record,
        )
    )

    if policy_match:
        policy = policy_match.group(1).lower()
        if policy == "none":
            findings.append(
                Finding(
                    category="dmarc",
                    title="DMARC policy",
                    status=FindingStatus.INCORRECT,
                    message="Policy is p=none (monitor only).",
                    recommendation="After validating reports, move to p=quarantine or p=reject.",
                )
            )
        else:
            findings.append(
                Finding(
                    category="dmarc",
                    title="DMARC policy",
                    status=FindingStatus.CORRECT,
                    message=f"Policy is p={policy}.",
                )
            )
    else:
        findings.append(
            Finding(
                category="dmarc",
                title="DMARC policy missing",
                status=FindingStatus.INCORRECT,
                message="DMARC record has no p= policy.",
                recommendation="Add p=none|quarantine|reject.",
            )
        )

    if rua:
        findings.append(
            Finding(
                category="dmarc",
                title="DMARC rua",
                status=FindingStatus.CORRECT,
                message=rua.group(1).strip(),
            )
        )
    else:
        findings.append(
            Finding(
                category="dmarc",
                title="DMARC rua missing",
                status=FindingStatus.INFO,
                message="No aggregate report address (rua=).",
                recommendation="Add rua=mailto:reports@yourdomain so you can see failures.",
            )
        )

    if ruf:
        findings.append(
            Finding(
                category="dmarc",
                title="DMARC ruf",
                status=FindingStatus.INFO,
                message=ruf.group(1).strip(),
            )
        )

    if pct:
        findings.append(
            Finding(
                category="dmarc",
                title="DMARC percentage",
                status=FindingStatus.INFO,
                message=f"pct={pct.group(1)}",
            )
        )

    return {"findings": findings, "record": record, "probe_ok": True}


def check_mx(
    domain: str,
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Check MX records exist and list priorities."""
    resolved = resolve_records(
        domain, nameserver=nameserver, timeout=timeout, record_types=("MX",)
    )
    findings: list[Finding] = []
    if not resolved["probe_ok"]:
        detail = "; ".join(resolved["errors"][:3]) or "DNS probe failed"
        return {
            "findings": [probe_failed_finding("mx", "MX check inconclusive", detail)],
            "records": [],
            "probe_ok": False,
        }
    records = resolved["records"]
    if not records:
        findings.append(
            Finding(
                category="mx",
                title="MX records",
                status=FindingStatus.MISSING,
                message="No MX records found — inbound email will fail.",
                recommendation="Add MX records for your mail provider (Microsoft 365, Google, etc.).",
            )
        )
    else:
        ordered = sorted(records, key=lambda r: r.priority if r.priority is not None else 999)
        msg = "; ".join(f"{r.priority} {r.value}" for r in ordered)
        findings.append(
            Finding(
                category="mx",
                title="MX records",
                status=FindingStatus.CORRECT,
                message=msg,
                details={"hosts": [r.value for r in ordered]},
            )
        )
    return {"findings": findings, "records": records, "probe_ok": True}


def check_smtp_ports(
    hosts: list[str],
    ports: tuple[int, ...] = (25, 465, 587),
    timeout: float = 5.0,
) -> list[Finding]:
    """TCP connect probe only — does not send mail."""
    findings: list[Finding] = []
    if not hosts:
        return [
            Finding(
                category="smtp",
                title="SMTP connectivity",
                status=FindingStatus.INFO,
                message="Skipped — no MX hosts to probe.",
            )
        ]

    host = hosts[0]
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                findings.append(
                    Finding(
                        category="smtp",
                        title=f"SMTP port {port}",
                        status=FindingStatus.CORRECT,
                        message=f"TCP connect to {host}:{port} succeeded.",
                    )
                )
        except OSError as exc:
            if is_probe_failure(exc):
                findings.append(
                    probe_failed_finding(
                        "smtp",
                        f"SMTP port {port} check inconclusive",
                        f"Could not connect to {host}:{port}: {exc}",
                    )
                )
                continue
            findings.append(
                Finding(
                    category="smtp",
                    title=f"SMTP port {port}",
                    status=FindingStatus.INFO if port == 25 else FindingStatus.INCORRECT,
                    message=f"Could not connect to {host}:{port}: {exc}",
                    recommendation=(
                        "Port 25 is often blocked on residential/ISP networks; "
                        "465/587 failures may indicate firewall or wrong MX host."
                    ),
                )
            )
    return findings


def check_sendgrid(
    domain: str,
    spf_records: list[str],
    dkim_found: list[str],
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
) -> list[Finding]:
    """SendGrid domain authentication / link branding DNS checklist."""
    findings: list[Finding] = []
    spf_joined = " ".join(spf_records).lower()

    if "include:sendgrid.net" in spf_joined:
        findings.append(
            Finding(
                category="sendgrid",
                title="SendGrid SPF include",
                status=FindingStatus.CORRECT,
                message="SPF includes include:sendgrid.net.",
            )
        )
    else:
        findings.append(
            Finding(
                category="sendgrid",
                title="SendGrid SPF include",
                status=FindingStatus.MISSING,
                message="SPF does not include include:sendgrid.net.",
                recommendation="Add include:sendgrid.net to the domain SPF if you send via SendGrid.",
            )
        )

    sg_selectors = [s for s in ("s1", "s2") if s in dkim_found]
    if sg_selectors:
        findings.append(
            Finding(
                category="sendgrid",
                title="SendGrid DKIM",
                status=FindingStatus.CORRECT,
                message="Found selectors: " + ", ".join(sg_selectors),
            )
        )
    else:
        # Also accept CNAMEs s1/s2._domainkey pointing at sendgrid.net
        cname_ok: list[str] = []
        resolver = _resolver(nameserver, timeout)
        for selector in ("s1", "s2"):
            name = f"{selector}._domainkey.{domain}"
            try:
                answers = resolver.resolve(name, "CNAME")
                for rdata in answers:
                    target = str(rdata.target).rstrip(".").lower()
                    if "sendgrid.net" in target:
                        cname_ok.append(selector)
            except Exception:  # noqa: BLE001
                continue
        if cname_ok:
            findings.append(
                Finding(
                    category="sendgrid",
                    title="SendGrid DKIM",
                    status=FindingStatus.CORRECT,
                    message="CNAME selectors point to SendGrid: " + ", ".join(cname_ok),
                )
            )
        else:
            findings.append(
                Finding(
                    category="sendgrid",
                    title="SendGrid DKIM",
                    status=FindingStatus.MISSING,
                    message="SendGrid DKIM selectors s1/s2 not found.",
                    recommendation="In SendGrid → Settings → Sender Authentication, add Domain Authentication and create s1/s2 CNAME records.",
                )
            )

    # Link branding hostnames are customer-specific. Probe only a tiny common set
    # with a short timeout so scans stay fast on slow/blocked DNS networks.
    link_hits: list[str] = []
    short = _resolver(nameserver, min(timeout, 2.0))
    candidates = [f"url1000.{domain}", f"em1000.{domain}", f"links.{domain}"]
    for host in candidates:
        try:
            answers = short.resolve(host, "CNAME")
            for rdata in answers:
                target = str(rdata.target).rstrip(".").lower()
                if "sendgrid.net" in target:
                    link_hits.append(f"{host} → {target}")
        except Exception:  # noqa: BLE001
            continue

    if link_hits:
        findings.append(
            Finding(
                category="sendgrid",
                title="SendGrid link branding",
                status=FindingStatus.CORRECT,
                message="; ".join(link_hits[:5]),
            )
        )
    else:
        findings.append(
            Finding(
                category="sendgrid",
                title="SendGrid link branding",
                status=FindingStatus.INFO,
                message="No common link-branding CNAMEs detected (optional; hostnames vary per SendGrid setup).",
                recommendation="In SendGrid → Sender Authentication → Link Branding, copy the exact CNAMEs provided.",
            )
        )

    findings.append(
        Finding(
            category="sendgrid",
            title="SendGrid reverse DNS",
            status=FindingStatus.INFO,
            message="PTR/rDNS for SendGrid shared IPs is managed by SendGrid; for dedicated IPs set PTR at your host.",
            recommendation="In SendGrid, complete reverse DNS for any dedicated IP.",
        )
    )

    return findings


def check_email(
    domain: str,
    dkim_selectors: str = "s1,s2,em,default",
    nameserver: Optional[str] = None,
    timeout: float = 10.0,
    probe_smtp: bool = True,
) -> dict[str, Any]:
    """Run full email authentication suite for a domain."""
    domain = domain.strip().lower().rstrip(".")
    selectors = [s.strip() for s in dkim_selectors.split(",") if s.strip()]

    apex = _txt_lookup(domain, nameserver, timeout)
    if not apex["probe_ok"]:
        finding = probe_failed_finding(
            "spf",
            "Email DNS checks inconclusive",
            apex["error"] or "Could not query DNS for email records",
        )
        return {
            "status": HealthStatus.UNKNOWN,
            "findings": [finding],
            "probe_ok": False,
            "raw": {"probe_failed": True, "error": apex["error"]},
        }

    spf = parse_spf(apex["records"])
    dkim = check_dkim(domain, selectors, nameserver=nameserver, timeout=timeout)
    dmarc = check_dmarc(domain, nameserver=nameserver, timeout=timeout)
    mx = check_mx(domain, nameserver=nameserver, timeout=timeout)

    findings: list[Finding] = []
    findings.extend(spf["findings"])
    findings.extend(dkim["findings"])
    findings.extend(dmarc["findings"])
    findings.extend(mx["findings"])

    # Only run SMTP / SendGrid extras when MX DNS itself was reachable.
    if probe_smtp and mx.get("probe_ok", True):
        hosts = [r.value for r in mx.get("records", [])]
        findings.extend(check_smtp_ports(hosts, timeout=min(timeout, 5.0)))

    if mx.get("probe_ok", True) and dkim.get("probe_ok", True):
        findings.extend(
            check_sendgrid(
                domain,
                spf_records=spf.get("records", []),
                dkim_found=dkim.get("found_selectors", []),
                nameserver=nameserver,
                timeout=timeout,
            )
        )
    else:
        findings.append(
            probe_failed_finding(
                "sendgrid",
                "SendGrid checks skipped",
                "DNS probe was unreliable, so SendGrid records were not judged missing.",
            )
        )

    auth_findings = [
        f for f in findings if f.category in {"spf", "dkim", "dmarc", "mx", "sendgrid"}
    ]
    status = aggregate_status(auth_findings)
    return {
        "status": status,
        "findings": findings,
        "probe_ok": True,
        "raw": {
            "spf": spf.get("records"),
            "dkim_selectors_found": dkim.get("found_selectors"),
            "dmarc": dmarc.get("record"),
            "mx": [r.value for r in mx.get("records", [])],
        },
    }
