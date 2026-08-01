"""Core domain entities for Website Health Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class HealthStatus(str, Enum):
    """Overall health of a check or website."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """Aggregated risk shown on the dashboard."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class FindingStatus(str, Enum):
    """Used especially for email/SendGrid checklist rows."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    MISSING = "missing"
    INFO = "info"
    # Local Wi‑Fi/DNS/timeout prevented a reliable check — do not treat as site failure.
    INCONCLUSIVE = "inconclusive"


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


@dataclass
class Customer:
    """A customer who owns one or more websites."""

    name: str
    id: Optional[int] = None
    notes: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Website:
    """A website/domain under monitoring."""

    url: str
    domain: str
    display_name: str
    id: Optional[int] = None
    customer_id: Optional[int] = None
    dkim_selectors: str = "s1,s2,em,default"
    check_interval: str = "manual"  # manual|hourly|every_6_hours|daily|weekly
    created_at: datetime = field(default_factory=utc_now)
    last_checked_at: Optional[datetime] = None


@dataclass
class Finding:
    """A single check result with human-readable guidance."""

    category: str
    title: str
    status: FindingStatus
    message: str
    recommendation: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DnsRecord:
    """One DNS resource record."""

    rtype: str
    name: str
    value: str
    ttl: Optional[int] = None
    priority: Optional[int] = None


@dataclass
class DnsSnapshot:
    """Point-in-time DNS records for a domain."""

    website_id: int
    records: list[DnsRecord]
    id: Optional[int] = None
    captured_at: datetime = field(default_factory=utc_now)


@dataclass
class HealthCheckResult:
    """Full scan result for one website."""

    website_id: int
    overall_status: HealthStatus = HealthStatus.UNKNOWN
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    website_status: HealthStatus = HealthStatus.UNKNOWN
    ssl_status: HealthStatus = HealthStatus.UNKNOWN
    domain_status: HealthStatus = HealthStatus.UNKNOWN
    dns_status: HealthStatus = HealthStatus.UNKNOWN
    email_status: HealthStatus = HealthStatus.UNKNOWN
    response_time_ms: Optional[float] = None
    findings: list[Finding] = field(default_factory=list)
    dns_records: list[DnsRecord] = field(default_factory=list)
    error_message: str = ""
    duration_ms: Optional[float] = None
    id: Optional[int] = None
    checked_at: datetime = field(default_factory=utc_now)
    raw: dict[str, Any] = field(default_factory=dict)
