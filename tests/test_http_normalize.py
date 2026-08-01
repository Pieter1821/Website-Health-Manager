"""HTTP normalize + redirect / client-error branches (offline)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from whm.domain.models import FindingStatus, HealthStatus
from whm.infrastructure.http_checker import check_website, normalize_url


def test_normalize_url_basics():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("https://Example.com/path/?q=1") == "https://example.com/path/"
    with pytest.raises(ValueError):
        normalize_url("ftp://example.com")
    with pytest.raises(ValueError):
        normalize_url("not-a-domain")


def _response(status_code, url="https://example.com/", headers=None, is_redirect=None):
    response = MagicMock()
    response.status_code = status_code
    response.is_redirect = (
        status_code in {301, 302, 303, 307, 308}
        if is_redirect is None
        else is_redirect
    )
    response.url = url
    response.headers = headers or {}
    return response


def test_http_404_is_warning():
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.return_value = _response(404)
        result = check_website("https://example.com", timeout=1)
    assert result["status"] == HealthStatus.WARNING
    assert any(f.title == "Client error response" for f in result["findings"])


def test_http_broken_redirect():
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.return_value = _response(302, headers={})
        result = check_website("https://example.com", timeout=1)
    assert any(f.title == "Broken redirect" for f in result["findings"])


def test_http_redirect_loop():
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value

        def side_effect(method, url):
            # Always redirect to the same absolute URL.
            return _response(
                302,
                url=url,
                headers={"location": "https://example.com/loop"},
            )

        client.request.side_effect = side_effect
        result = check_website("https://example.com/loop", timeout=1)
    assert any(f.title == "Redirect loop" for f in result["findings"])
    assert result["status"] != HealthStatus.CRITICAL or any(
        f.status == FindingStatus.INCORRECT for f in result["findings"]
    )


def test_http_final_http_warns_about_https():
    with patch("whm.infrastructure.http_checker.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.request.return_value = _response(200, url="http://example.com/")
        result = check_website("http://example.com", timeout=1)
    assert any("HTTPS" in f.title or "HTTPS" in f.message for f in result["findings"])
    assert result["status"] in {HealthStatus.WARNING, HealthStatus.HEALTHY}
