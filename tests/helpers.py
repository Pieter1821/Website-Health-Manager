"""Shared offline stubs for scan orchestration tests (do not import conftest)."""

from __future__ import annotations

from whm.domain.models import DnsRecord, Finding, FindingStatus, HealthStatus


def healthy_check(**extra):
    """Minimal checker return shape used by scan orchestration stubs."""
    payload = {
        "status": HealthStatus.HEALTHY,
        "findings": [],
        "response_time_ms": 42.0,
        "records": [],
        "probe_ok": True,
        "raw": {},
    }
    payload.update(extra)
    return payload


def dns_with_records(domain: str = "example.com"):
    return healthy_check(
        records=[
            DnsRecord("A", domain, "203.0.113.10"),
            DnsRecord("NS", domain, "ns1.example.net"),
        ],
        raw={"domain": domain},
    )


def warn_finding(category: str = "ssl", title: str = "Soon"):
    return Finding(category, title, FindingStatus.INCORRECT, "needs work", "Fix it")
