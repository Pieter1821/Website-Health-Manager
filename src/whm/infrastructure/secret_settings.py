"""Settings keys that must never leave the local PC (not synced to D1)."""

from __future__ import annotations

SECRET_SETTING_KEYS: frozenset[str] = frozenset(
    {
        "smtp_password",
        "smtp_username",
        "smtp_host",
        "mail_from",
        "mail_to",
        "slack_webhook",
        "discord_webhook",
        "teams_webhook",
        "generic_webhook",
    }
)
