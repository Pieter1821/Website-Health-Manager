"""Plain-language labels for non-technical users."""

from __future__ import annotations

from typing import TYPE_CHECKING

from whm.domain.models import FindingStatus, HealthStatus, RiskLevel
from whm.domain.status import site_facing_status

if TYPE_CHECKING:
    from whm.domain.models import HealthCheckResult

STATUS_PLAIN = {
    HealthStatus.HEALTHY: "Looks good",
    HealthStatus.WARNING: "Worth a look",
    HealthStatus.CRITICAL: "Needs a fix",
    HealthStatus.UNKNOWN: "Couldn’t finish",
}

RISK_PLAIN = {
    RiskLevel.LOW: "Low",
    RiskLevel.MEDIUM: "Medium",
    RiskLevel.HIGH: "High",
    RiskLevel.UNKNOWN: "Not sure yet",
}

FINDING_PLAIN = {
    FindingStatus.CORRECT: "OK",
    FindingStatus.INCORRECT: "Review",
    FindingStatus.MISSING: "Not set up",
    FindingStatus.INFO: "Info",
    FindingStatus.INCONCLUSIVE: "Couldn’t finish",
}

CATEGORY_PLAIN = {
    "website": "Website",
    "ssl": "Security certificate (HTTPS)",
    "domain": "Domain registration",
    "dns": "Web address settings (DNS)",
    "spf": "Email sender permission (SPF)",
    "dkim": "Email signature (DKIM)",
    "dmarc": "Email policy (DMARC)",
    "mx": "Incoming email (MX)",
    "smtp": "Mail server connection",
    "sendgrid": "SendGrid email setup",
    "security": "Website security settings",
    "performance": "Speed",
    "hosting": "Hosting provider",
    "technology": "Website technology",
}

CATEGORY_TIP = {
    "website": "Can people open the site in a browser?",
    "ssl": "The padlock certificate that keeps the site secure.",
    "domain": "The website name registration (like a lease on the name).",
    "dns": "The address book that points web and email to the right place.",
    "spf": "Who may send mail for this domain — only judged when the domain looks mail-active.",
    "dkim": "Digital stamp on outbound mail — only judged when the domain looks mail-active.",
    "dmarc": "Spoofing policy — only judged when the domain looks mail-active.",
    "mx": "Incoming mail hosts. Missing MX is fine for website-only domains.",
    "smtp": "Optional mail-port probe — usually skipped; not proof mail is broken.",
    "sendgrid": "Only if this domain already uses SendGrid.",
    "hosting": "Clues about who hosts the website.",
    "technology": "Clues about how the website is built.",
}


def status_plain(status: HealthStatus) -> str:
    return STATUS_PLAIN.get(status, status.value)


def website_plain(status: HealthStatus, *, probe_failed: bool = False) -> str:
    """Labels for the Web / Opens column (not the same wording as overall Status)."""
    if probe_failed or status == HealthStatus.UNKNOWN:
        return "Couldn’t check"
    if status == HealthStatus.CRITICAL:
        return "Can’t reach"
    if status == HealthStatus.WARNING:
        return "Opens (issues)"
    if status == HealthStatus.HEALTHY:
        return "Opens"
    return status_plain(status)


def risk_plain(risk: RiskLevel) -> str:
    return RISK_PLAIN.get(risk, risk.value)


def finding_plain(status: FindingStatus) -> str:
    return FINDING_PLAIN.get(status, status.value)


def category_plain(category: str) -> str:
    return CATEGORY_PLAIN.get(category, category.replace("_", " ").title())


def category_tip(category: str) -> str:
    return CATEGORY_TIP.get(
        category,
        "This part of the website check needs attention.",
    )


def _area_statuses(result: HealthCheckResult) -> list[tuple[str, HealthStatus]]:
    # Email is not part of the list Status column.
    return [
        ("Website", result.website_status),
        ("Certificate", result.ssl_status),
        ("Domain", result.domain_status),
        ("DNS", result.dns_status),
    ]


def overall_why(result: HealthCheckResult) -> str:
    """One short line under Status — which area is the problem."""
    status = site_facing_status(
        result.website_status,
        result.ssl_status,
        result.domain_status,
        result.dns_status,
    )
    if status == HealthStatus.HEALTHY:
        return "No action needed"
    if status == HealthStatus.UNKNOWN:
        return "Try again later"

    target = (
        HealthStatus.CRITICAL
        if status == HealthStatus.CRITICAL
        else HealthStatus.WARNING
    )
    bad = [name for name, area in _area_statuses(result) if area == target]
    if not bad:
        return "Open Problems & fixes"
    if len(bad) == 1:
        return f"Check {bad[0]}"
    return f"Check {bad[0]} (+{len(bad) - 1} more)"


def overall_summary(status: HealthStatus, display_name: str) -> str:
    if status == HealthStatus.HEALTHY:
        return f"{display_name} looks healthy."
    if status == HealthStatus.WARNING:
        return f"{display_name} is working, with a few things to improve. See Problems & fixes."
    if status == HealthStatus.CRITICAL:
        return (
            f"{display_name} needs a fix soon "
            "(site not opening, or certificate/domain about to expire). "
            "See Problems & fixes."
        )
    return f"Couldn’t finish checking {display_name}. Try again when your internet is steady."
