"""Local cloud connection config (~/.whm/cloud.json)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def is_session_jwt(token: str) -> bool:
    """Desktop sessions are JWTs (three base64url segments). Bootstrap tokens are not."""
    parts = (token or "").split(".")
    return len(parts) == 3 and all(parts)


@dataclass
class CloudConfig:
    api_url: str
    api_token: str = ""
    username: str = ""
    session_expires_at: str = ""
    role: str = ""

    @property
    def enabled(self) -> bool:
        """Cloud mode when an API URL is configured."""
        return bool(self.api_url.strip())

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_url.strip() and self.api_token.strip())

    @property
    def has_session(self) -> bool:
        return self.has_credentials and is_session_jwt(self.api_token)

    @property
    def session_valid(self) -> bool:
        if not self.has_session:
            return False
        if not self.session_expires_at:
            return True
        try:
            exp = datetime.fromisoformat(self.session_expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return exp > datetime.now(timezone.utc)


def cloud_config_path() -> Path:
    return Path.home() / ".whm" / "cloud.json"


def load_cloud_config(*, allow_bootstrap_token: bool = True) -> Optional[CloudConfig]:
    """
    Load cloud API settings.

    Priority:
      1) WHM_API_URL (+ optional WHM_API_TOKEN) env vars
      2) ~/.whm/cloud.json

    Bootstrap / shared API tokens (non-JWT ``api_token``) are accepted only when
    ``allow_bootstrap_token`` is True (migrate / admin scripts). The desktop app
    must pass ``allow_bootstrap_token=False`` so a shared WHM_API_TOKEN in
    cloud.json cannot bypass email/password login.
    """
    env_url = (os.environ.get("WHM_API_URL") or "").strip().rstrip("/")
    env_token = (os.environ.get("WHM_API_TOKEN") or "").strip()
    if env_url:
        token = env_token
        if token and not allow_bootstrap_token and not is_session_jwt(token):
            token = ""
        return CloudConfig(api_url=env_url, api_token=token)

    path = cloud_config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    url = str(data.get("api_url") or "").strip().rstrip("/")
    if not url:
        return None
    session = str(data.get("session_token") or "").strip()
    legacy = str(data.get("api_token") or "").strip()
    expires_at = str(data.get("session_expires_at") or "").strip()
    token = ""
    if is_session_jwt(session) and _session_not_expired(expires_at):
        token = session
    elif is_session_jwt(legacy):
        token = legacy
    elif allow_bootstrap_token and legacy:
        token = legacy
    return CloudConfig(
        api_url=url,
        api_token=token,
        username=str(data.get("username") or "").strip(),
        session_expires_at=expires_at,
        role=str(data.get("role") or "").strip(),
    )


def _session_not_expired(expires_at: str) -> bool:
    if not expires_at:
        return True
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return exp > datetime.now(timezone.utc)


def save_cloud_config(
    api_url: str,
    api_token: str = "",
    *,
    username: str = "",
    session_expires_at: str = "",
    role: str = "",
) -> Path:
    """Persist cloud connection. Prefer session_token for JWT sessions."""
    path = cloud_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    payload: dict[str, Any] = {
        "api_url": api_url.strip().rstrip("/"),
    }
    token = api_token.strip()
    if token:
        if session_expires_at or is_session_jwt(token):
            payload["session_token"] = token
            if session_expires_at:
                payload["session_expires_at"] = session_expires_at
            # Drop legacy bootstrap token from the desktop config file.
            existing.pop("api_token", None)
        else:
            payload["api_token"] = token
    user = username.strip() or str(existing.get("username") or "")
    if user:
        payload["username"] = user
    if role.strip():
        payload["role"] = role.strip()
    elif existing.get("role") and "session_token" in payload:
        payload["role"] = existing["role"]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def clear_cloud_session() -> None:
    """Remove session credentials but keep api_url for re-login."""
    path = cloud_config_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    url = str(data.get("api_url") or "").strip().rstrip("/")
    username = str(data.get("username") or "").strip()
    if not url:
        return
    payload: dict[str, Any] = {"api_url": url}
    if username:
        payload["username"] = username
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
