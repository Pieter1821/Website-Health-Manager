"""Shared Settings labels and plain-language help (web + Tk)."""

from __future__ import annotations

# (key, label, tip for the i button, short hint under the field)
SETTINGS_FIELDS: list[tuple[str, str, str, str]] = [
    (
        "timeout_seconds",
        "Wait time (seconds)",
        "How long WHM waits for each website or DNS check before giving up. "
        "Increase this if your internet is slow and checks often say “Couldn’t finish”.",
        "Default is 10. Try 20 on a slow link.",
    ),
    (
        "dns_server",
        "DNS server (optional)",
        "Optional DNS server IP used for address checks "
        "(example: 1.1.1.1 or 8.8.8.8). Leave blank to use the computer’s normal DNS.",
        "Leave blank unless you need a specific DNS server.",
    ),
    (
        "check_interval",
        "Automatic checks",
        "How often WHM re-checks all sites while the app is running. "
        "Use manual if you only want checks when you press Check. "
        "The app must stay open for automatic checks to run.",
        "manual · hourly · every_6_hours · daily · weekly",
    ),
    (
        "notify_on",
        "When to alert",
        "When to send desktop, Slack/Teams/Discord, webhook, or email alerts after a check. "
        "critical = only “Needs a fix”; warning = “Worth a look” or worse; "
        "always = every finished check; never = no alerts.",
        "critical · warning · always · never",
    ),
    (
        "notify_desktop",
        "Desktop alerts",
        "Show a Windows notification popup when an alert fires. "
        "Turn this on if you want a Windows toast; turn it off if you only use Slack/email.",
        "1 = yes · 0 = no",
    ),
    (
        "export_folder",
        "Report folder",
        "Only used by the classic (Tk) window. The web UI always saves Excel/CSV into your Downloads folder.",
        "Example: exports",
    ),
    (
        "slack_webhook",
        "Slack webhook",
        "Paste a Slack Incoming Webhook URL to post alerts into a channel. "
        "Stored only on this computer (not synced to the cloud). Leave blank to skip Slack.",
        "https://hooks.slack.com/services/…",
    ),
    (
        "discord_webhook",
        "Discord webhook",
        "Paste a Discord channel webhook URL to post alerts. "
        "Stored only on this computer (not synced to the cloud). Leave blank to skip Discord.",
        "https://discord.com/api/webhooks/…",
    ),
    (
        "teams_webhook",
        "Teams webhook",
        "Paste a Microsoft Teams Incoming Webhook URL to post alerts to a channel. "
        "Stored only on this computer (not synced to the cloud). Leave blank to skip Teams.",
        "https://….webhook.office.com/…",
    ),
    (
        "generic_webhook",
        "Generic webhook",
        "Any HTTPS URL that accepts a JSON POST. Stored only on this computer (not synced to the cloud). "
        "Leave blank to skip.",
        "https://…",
    ),
    (
        "smtp_host",
        "SMTP host",
        "Mail server used to send email alerts (example: smtp.office365.com or smtp.gmail.com). "
        "Stored only on this computer. Leave blank if you do not want email alerts.",
        "Needed only for email alerts",
    ),
    (
        "smtp_port",
        "SMTP port",
        "Port for the mail server. 587 is the usual choice for secure email (STARTTLS).",
        "Usually 587",
    ),
    (
        "smtp_username",
        "SMTP username",
        "Login name for the mail server, if it requires sign-in. Often the same as the From email.",
        "",
    ),
    (
        "smtp_password",
        "SMTP password",
        "Password or app password for the mail server. Always stored only on this computer "
        "(never synced to Cloudflare D1), even when websites use cloud storage.",
        "Use an app password when your provider offers one",
    ),
    (
        "mail_from",
        "From email",
        "The From address shown on alert emails. Must be allowed by your mail server.",
        "you@yourcompany.com",
    ),
    (
        "mail_to",
        "To email",
        "Where alert emails are delivered — usually your support or ops inbox. "
        "You can put one address here.",
        "support@yourcompany.com",
    ),
]
