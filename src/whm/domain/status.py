"""Pure rules for mapping expiry / findings into health statuses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from whm.domain.models import Finding, FindingStatus, HealthStatus, RiskLevel

if TYPE_CHECKING:
    from whm.domain.models import HealthCheckResult

# Alert ladder from the PRD (days remaining).
EXPIRY_THRESHOLDS = (90, 60, 30, 14, 7)


def days_to_status(days_remaining: Optional[int]) -> HealthStatus:
    """Map days-until-expiry to Healthy / Warning / Critical."""
    if days_remaining is None:
        return HealthStatus.UNKNOWN
    if days_remaining < 0:
        return HealthStatus.CRITICAL
    if days_remaining <= 14:
        return HealthStatus.CRITICAL
    if days_remaining <= 30:
        return HealthStatus.WARNING
    return HealthStatus.HEALTHY


def finding_to_status(finding: Finding) -> HealthStatus:
    """Map a finding row to overall health contribution."""
    if finding.status == FindingStatus.CORRECT:
        return HealthStatus.HEALTHY
    if finding.status == FindingStatus.INFO:
        return HealthStatus.HEALTHY
    if finding.status == FindingStatus.INCONCLUSIVE:
        return HealthStatus.UNKNOWN
    if finding.details.get("probe_failed"):
        return HealthStatus.UNKNOWN
    if finding.status == FindingStatus.INCORRECT:
        return HealthStatus.WARNING
    if finding.status == FindingStatus.MISSING:
        # Only MX missing usually stops mail. SPF/DKIM/DMARC/SendGrid gaps
        # are common even when mail still works — treat those as amber.
        if finding.category == "mx":
            return HealthStatus.CRITICAL
        return HealthStatus.WARNING
    return HealthStatus.UNKNOWN


_STATUS_RANK = {
    HealthStatus.UNKNOWN: 0,
    HealthStatus.HEALTHY: 1,
    HealthStatus.WARNING: 2,
    HealthStatus.CRITICAL: 3,
}


def worst_status(statuses: Iterable[HealthStatus]) -> HealthStatus:
    """Return the most severe status from a collection."""
    worst = HealthStatus.UNKNOWN
    for status in statuses:
        if _STATUS_RANK[status] > _STATUS_RANK[worst]:
            worst = status
    return worst


def worst_known_status(statuses: Iterable[HealthStatus]) -> HealthStatus:
    """
    Prefer real results over UNKNOWN.

    If every check was inconclusive (bad Wi‑Fi), return UNKNOWN instead of inventing Critical.
    """
    known = [s for s in statuses if s != HealthStatus.UNKNOWN]
    if not known:
        return HealthStatus.UNKNOWN
    return worst_status(known)


def site_facing_status(
    website: HealthStatus,
    ssl: HealthStatus,
    domain: HealthStatus,
    dns: HealthStatus,
) -> HealthStatus:
    """
    Overall status for the websites list / Status column / History.

    Email auth (SPF/DKIM/DMARC/MX) is not part of site health — older stored
    overall_status values that included email must be recomputed this way.
    """
    return worst_known_status([website, ssl, domain, dns])


def display_overall(result: HealthCheckResult) -> HealthStatus:
    """Site-facing overall for UI (list, detail summary, history rows)."""
    return site_facing_status(
        result.website_status,
        result.ssl_status,
        result.domain_status,
        result.dns_status,
    )


def aggregate_status(findings: Iterable[Finding]) -> HealthStatus:
    """Combine many findings into one HealthStatus, ignoring inconclusive probe noise."""
    findings = list(findings)
    known = [
        f
        for f in findings
        if f.status != FindingStatus.INCONCLUSIVE and not f.details.get("probe_failed")
    ]
    if not known:
        return HealthStatus.UNKNOWN
    return worst_status(finding_to_status(f) for f in known)


def status_to_risk(status: HealthStatus) -> RiskLevel:
    """Dashboard risk column mapping."""
    mapping = {
        HealthStatus.HEALTHY: RiskLevel.LOW,
        HealthStatus.WARNING: RiskLevel.MEDIUM,
        HealthStatus.CRITICAL: RiskLevel.HIGH,
        HealthStatus.UNKNOWN: RiskLevel.UNKNOWN,
    }
    return mapping[status]


def status_emoji(status: HealthStatus) -> str:
    """Simple visual indicator for tree views / reports."""
    return {
        HealthStatus.HEALTHY: "OK",
        HealthStatus.WARNING: "WARN",
        HealthStatus.CRITICAL: "CRIT",
        HealthStatus.UNKNOWN: "?",
    }[status]
