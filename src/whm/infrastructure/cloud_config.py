"""Local cloud connection config (~/.whm/cloud.json)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class CloudConfig:
    api_url: str
    api_token: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_url.strip() and self.api_token.strip())


def cloud_config_path() -> Path:
    return Path.home() / ".whm" / "cloud.json"


def load_cloud_config() -> Optional[CloudConfig]:
    """
    Load cloud API settings.

    Priority:
      1) WHM_API_URL + WHM_API_TOKEN env vars
      2) ~/.whm/cloud.json
    """
    env_url = (os.environ.get("WHM_API_URL") or "").strip().rstrip("/")
    env_token = (os.environ.get("WHM_API_TOKEN") or "").strip()
    if env_url and env_token:
        return CloudConfig(api_url=env_url, api_token=env_token)

    path = cloud_config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    url = str(data.get("api_url") or "").strip().rstrip("/")
    token = str(data.get("api_token") or "").strip()
    if not url or not token:
        return None
    return CloudConfig(api_url=url, api_token=token)


def save_cloud_config(api_url: str, api_token: str) -> Path:
    path = cloud_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_url": api_url.strip().rstrip("/"),
        "api_token": api_token.strip(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
