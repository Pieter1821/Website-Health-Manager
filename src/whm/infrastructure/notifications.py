"""Desktop + webhook notifications (Phases 2 and 6)."""

from __future__ import annotations

import json
import logging
import smtplib
import subprocess
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any

from whm.domain.models import HealthCheckResult, HealthStatus, Website
from whm.presentation.copy import overall_summary, status_plain

logger = logging.getLogger(__name__)


def should_notify(result: HealthCheckResult, notify_on: str) -> bool:
    """notify_on: critical | warning | always | never"""
    if notify_on == "never":
        return False
    if notify_on == "always":
        return True
    if notify_on == "warning":
        return result.overall_status in {HealthStatus.WARNING, HealthStatus.CRITICAL}
    return result.overall_status == HealthStatus.CRITICAL


def format_message(website: Website, result: HealthCheckResult) -> str:
    return (
        f"{website.display_name}: {status_plain(result.overall_status)}\n"
        f"{overall_summary(result.overall_status, website.display_name)}"
    )


def notify_desktop(title: str, message: str) -> None:
    """Best-effort Windows toast via PowerShell; no-op if unavailable."""
    try:
        # Keep script short; avoid complex escaping by using base-ish replacement.
        safe_title = title.replace("'", "")
        safe_msg = message.replace("'", "").replace("\n", " ")
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            f"$template.GetElementsByTagName('text')[0].AppendChild($template.CreateTextNode('{safe_title}')) > $null; "
            f"$template.GetElementsByTagName('text')[1].AppendChild($template.CreateTextNode('{safe_msg}')) > $null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Website Health Manager')"
            ".Show($toast);"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            timeout=8,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Desktop notification skipped: %s", exc)


def _post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def notify_slack(webhook: str, text: str) -> None:
    if not webhook.strip():
        return
    _post_json(webhook.strip(), {"text": text})


def notify_discord(webhook: str, text: str) -> None:
    if not webhook.strip():
        return
    _post_json(webhook.strip(), {"content": text[:1900]})


def notify_teams(webhook: str, text: str) -> None:
    if not webhook.strip():
        return
    _post_json(
        webhook.strip(),
        {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "Website Health Manager",
            "themeColor": "0076D7",
            "title": "Website Health Manager",
            "text": text,
        },
    )


def notify_generic_webhook(webhook: str, website: Website, result: HealthCheckResult) -> None:
    if not webhook.strip():
        return
    _post_json(
        webhook.strip(),
        {
            "source": "website-health-manager",
            "website": website.display_name,
            "domain": website.domain,
            "status": result.overall_status.value,
            "risk": result.risk_level.value,
            "message": format_message(website, result),
            "checked_at": result.checked_at.isoformat(),
        },
    )


def notify_email(
    *,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    mail_from: str,
    mail_to: str,
    subject: str,
    body: str,
    use_tls: bool = True,
) -> None:
    if not (smtp_host and mail_to and mail_from):
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(body)
    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)


def dispatch_notifications(
    website: Website,
    result: HealthCheckResult,
    settings: dict[str, str],
) -> list[str]:
    """Send configured notifications. Returns human-readable send results."""
    notify_on = settings.get("notify_on", "critical")
    if not should_notify(result, notify_on):
        return []

    text = format_message(website, result)
    sent: list[str] = []

    if settings.get("notify_desktop", "1") in {"1", "true", "yes"}:
        try:
            notify_desktop("Website Health Manager", text)
            sent.append("desktop")
        except Exception as exc:  # noqa: BLE001
            logger.info("Desktop notify failed: %s", exc)

    try:
        if settings.get("slack_webhook"):
            notify_slack(settings["slack_webhook"], text)
            sent.append("slack")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("Slack notify failed: %s", exc)

    try:
        if settings.get("discord_webhook"):
            notify_discord(settings["discord_webhook"], text)
            sent.append("discord")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("Discord notify failed: %s", exc)

    try:
        if settings.get("teams_webhook"):
            notify_teams(settings["teams_webhook"], text)
            sent.append("teams")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("Teams notify failed: %s", exc)

    try:
        if settings.get("generic_webhook"):
            notify_generic_webhook(settings["generic_webhook"], website, result)
            sent.append("webhook")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("Webhook notify failed: %s", exc)

    try:
        if settings.get("smtp_host") and settings.get("mail_to"):
            notify_email(
                smtp_host=settings.get("smtp_host", ""),
                smtp_port=int(settings.get("smtp_port", "587") or "587"),
                username=settings.get("smtp_username", ""),
                password=settings.get("smtp_password", ""),
                mail_from=settings.get("mail_from", settings.get("smtp_username", "")),
                mail_to=settings.get("mail_to", ""),
                subject=f"[WHM] {website.display_name}: {status_plain(result.overall_status)}",
                body=text,
            )
            sent.append("email")
    except Exception as exc:  # noqa: BLE001
        logger.info("Email notify failed: %s", exc)

    return sent
