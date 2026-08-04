"""Cloud API client auth helpers (login / register)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from whm.infrastructure.cloud_client import CloudApiClient, CloudApiError
from whm.infrastructure.cloud_config import CloudConfig


def _client() -> CloudApiClient:
    return CloudApiClient(CloudConfig(api_url="https://example.workers.dev", api_token=""))


def test_login_posts_public_auth_body() -> None:
    client = _client()
    with patch.object(client, "post", return_value={"status": "ok"}) as post:
        client.login("You@Example.com", "secret-password")
    post.assert_called_once_with(
        "/api/auth/login",
        {
            "email": "You@Example.com",
            "username": "You@Example.com",
            "password": "secret-password",
        },
        auth=False,
    )


def test_register_posts_public_auth_body() -> None:
    client = _client()
    with patch.object(client, "post", return_value={"status": "ok"}) as post:
        client.register("new@example.com", "long-enough")
    post.assert_called_once_with(
        "/api/auth/register",
        {
            "email": "new@example.com",
            "username": "new@example.com",
            "password": "long-enough",
        },
        auth=False,
    )


def test_register_propagates_api_error() -> None:
    client = _client()
    with patch.object(
        client,
        "post",
        side_effect=CloudApiError("Email already exists", 409),
    ):
        with pytest.raises(CloudApiError) as exc:
            client.register("dup@example.com", "long-enough")
    assert exc.value.status_code == 409
    assert "already exists" in str(exc.value).lower()
