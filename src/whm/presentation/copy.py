"""Plain-language labels for non-technical users."""

from __future__ import annotations

from whm.domain.models import FindingStatus, HealthStatus, RiskLevel

STATUS_PLAIN = {
    HealthStatus.HEALTHY: "Looks good",
    HealthStatus.WARNING: "Needs attention",
    HealthStatus.CRITICAL: "Something's wrong",
    HealthStatus.UNKNOWN: "Couldn't check",
}

RISK_PLAIN = {
    RiskLevel.LOW: "Low",
    RiskLevel.MEDIUM: "Medium",
    RiskLevel.HIGH: "High",
    RiskLevel.UNKNOWN: "Not sure yet",
}

FINDING_PLAIN = {
    FindingStatus.CORRECT: "OK",
    FindingStatus.INCORRECT: "Needs fixing",
    FindingStatus.MISSING: "Missing",
    FindingStatus.INFO: "Info",
    FindingStatus.INCONCLUSIVE: "Couldn't check",
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
    "spf": "Who is allowed to send email for this domain.",
    "dkim": "A digital stamp that proves the email really came from you.",
    "dmarc": "What receivers should do with forged or failing email.",
    "mx": "Where incoming email for this domain should be delivered.",
    "smtp": "Whether the mail server answers on common ports.",
    "sendgrid": "SendGrid DNS records so customer mail can send properly.",
    "hosting": "Clues about who hosts the website.",
    "technology": "Clues about how the website is built.",
}


def status_plain(status: HealthStatus) -> str:
    return STATUS_PLAIN.get(status, status.value)


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


def overall_summary(status: HealthStatus, display_name: str) -> str:
    if status == HealthStatus.HEALTHY:
        return f"{display_name} looks healthy."
    if status == HealthStatus.WARNING:
        return f"{display_name} works, but a few things should be fixed soon."
    if status == HealthStatus.CRITICAL:
        return f"{display_name} has problems that may stop the website or email from working."
    return (
        f"We couldn't fully check {display_name}. "
        "This often means your internet connection was unstable — try again."
    )
