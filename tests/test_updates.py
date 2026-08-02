"""GitHub Releases update helper."""

from __future__ import annotations

import httpx

from whm.infrastructure.updates import (
    check_for_update,
    is_newer,
    parse_version,
    update_info_dict,
)


def test_parse_version():
    assert parse_version("v0.1.2") == (0, 1, 2)
    assert parse_version("0.1.2") == (0, 1, 2)
    assert parse_version("") == (0,)


def test_is_newer():
    assert is_newer("0.1.3", "0.1.2")
    assert is_newer("v0.2.0", "0.1.9")
    assert not is_newer("0.1.2", "0.1.2")
    assert not is_newer("0.1.1", "0.1.2")


def test_check_for_update_picks_setup_asset():
    payload = {
        "tag_name": "v0.1.3",
        "name": "v0.1.3",
        "html_url": "https://github.com/example/repo/releases/tag/v0.1.3",
        "assets": [
            {
                "name": "WebsiteHealthManager.exe",
                "browser_download_url": "https://example.com/portable.exe",
            },
            {
                "name": "WebsiteHealthManager-Setup-0.1.3.exe",
                "browser_download_url": "https://example.com/setup.exe",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        info = check_for_update(current_version="0.1.2", client=client)
    assert info.update_available is True
    assert info.latest_version == "0.1.3"
    assert info.download_url == "https://example.com/setup.exe"
    assert update_info_dict(info)["current_version"] == "0.1.2"


def test_check_for_update_soft_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        info = check_for_update(current_version="0.1.2", client=client)
    assert info.update_available is False
    assert info.checked is False
    assert info.error
