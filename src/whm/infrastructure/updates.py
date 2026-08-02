"""Check GitHub Releases for a newer Website Health Manager build."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from whm import __version__ as APP_VERSION

GITHUB_OWNER = "Pieter1821"
GITHUB_REPO = "Website-Health-Manager"
RELEASES_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    download_url: str
    release_name: str
    checked: bool
    error: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """Parse 'v0.1.2' / '0.1.2' into a comparable tuple."""
    cleaned = (text or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer(latest: str, current: str) -> bool:
    """True when latest is strictly newer than current."""
    a = parse_version(latest)
    b = parse_version(current)
    # Pad to same length for compare.
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def _pick_download_url(assets: list[dict[str, Any]], html_url: str) -> str:
    names = [(a.get("name") or "", a.get("browser_download_url") or "") for a in assets]
    for name, url in names:
        if name.startswith("WebsiteHealthManager-Setup-") and name.endswith(".exe") and url:
            return url
    for name, url in names:
        if name == "WebsiteHealthManager.exe" and url:
            return url
    for name, url in names:
        if name.endswith(".exe") and url:
            return url
    return html_url or RELEASES_PAGE


def check_for_update(
    *,
    current_version: Optional[str] = None,
    timeout: float = 12.0,
    client: Optional[httpx.Client] = None,
) -> UpdateInfo:
    """
    Query GitHub Releases latest tag.

    Failures are soft: update_available=False with error set (app keeps working offline).
    """
    current = (current_version or APP_VERSION).strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"WebsiteHealthManager-Desktop/{current}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        res = http.get(RELEASES_LATEST, headers=headers)
        if res.status_code == 404:
            return UpdateInfo(
                current_version=current,
                latest_version=current,
                update_available=False,
                release_url=RELEASES_PAGE,
                download_url=RELEASES_PAGE,
                release_name="",
                checked=True,
                error="No releases published yet",
            )
        res.raise_for_status()
        data = res.json()
    except Exception as exc:  # noqa: BLE001 — network/API soft-fail
        return UpdateInfo(
            current_version=current,
            latest_version=current,
            update_available=False,
            release_url=RELEASES_PAGE,
            download_url=RELEASES_PAGE,
            release_name="",
            checked=False,
            error=str(exc) or "Could not reach GitHub",
        )
    finally:
        if owns_client:
            http.close()

    tag = str(data.get("tag_name") or "").strip()
    latest = tag.lstrip("vV") or current
    html_url = str(data.get("html_url") or RELEASES_PAGE)
    assets = data.get("assets") or []
    if not isinstance(assets, list):
        assets = []
    download = _pick_download_url(assets, html_url)
    available = is_newer(latest, current)
    return UpdateInfo(
        current_version=current,
        latest_version=latest,
        update_available=available,
        release_url=html_url,
        download_url=download,
        release_name=str(data.get("name") or tag),
        checked=True,
        error="",
    )


def update_info_dict(info: UpdateInfo) -> dict[str, Any]:
    return {
        "current_version": info.current_version,
        "latest_version": info.latest_version,
        "update_available": info.update_available,
        "release_url": info.release_url,
        "download_url": info.download_url,
        "release_name": info.release_name,
        "checked": info.checked,
        "error": info.error,
    }
