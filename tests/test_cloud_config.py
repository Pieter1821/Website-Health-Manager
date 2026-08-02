"""Cloud connection config helpers."""

from __future__ import annotations

import json
from pathlib import Path

from whm.infrastructure.cloud_config import (
    CloudConfig,
    clear_cloud_session,
    load_cloud_config,
    save_cloud_config,
)


def test_load_cloud_config_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WHM_API_URL", "https://example.workers.dev/")
    monkeypatch.setenv("WHM_API_TOKEN", "secret-token")
    monkeypatch.setattr(
        "whm.infrastructure.cloud_config.cloud_config_path",
        lambda: tmp_path / "cloud.json",
    )
    cfg = load_cloud_config()
    assert cfg is not None
    assert cfg.api_url == "https://example.workers.dev"
    assert cfg.api_token == "secret-token"
    assert cfg.enabled
    assert cfg.has_credentials


def test_save_and_load_cloud_config_file(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "cloud.json"
    monkeypatch.delenv("WHM_API_URL", raising=False)
    monkeypatch.delenv("WHM_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "whm.infrastructure.cloud_config.cloud_config_path",
        lambda: path,
    )
    save_cloud_config("https://api.example/", "tok")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["api_url"] == "https://api.example"
    assert data["api_token"] == "tok"
    cfg = load_cloud_config()
    assert cfg == CloudConfig(api_url="https://api.example", api_token="tok")


def test_session_token_roundtrip(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "cloud.json"
    monkeypatch.delenv("WHM_API_URL", raising=False)
    monkeypatch.delenv("WHM_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "whm.infrastructure.cloud_config.cloud_config_path",
        lambda: path,
    )
    jwt = "aaa.bbb.ccc"
    save_cloud_config(
        "https://api.example/",
        jwt,
        username="pieter",
        session_expires_at="2099-01-01T00:00:00Z",
        role="admin",
    )
    cfg = load_cloud_config(allow_bootstrap_token=False)
    assert cfg is not None
    assert cfg.api_token == jwt
    assert cfg.username == "pieter"
    assert cfg.role == "admin"
    assert cfg.session_valid
    clear_cloud_session()
    again = load_cloud_config(allow_bootstrap_token=False)
    assert again is not None
    assert again.api_url == "https://api.example"
    assert again.api_token == ""
    assert again.username == "pieter"


def test_desktop_ignores_bootstrap_token_in_file(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "cloud.json"
    path.write_text(
        json.dumps({"api_url": "https://api.example", "api_token": "not-a-jwt"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("WHM_API_URL", raising=False)
    monkeypatch.delenv("WHM_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "whm.infrastructure.cloud_config.cloud_config_path",
        lambda: path,
    )
    desktop = load_cloud_config(allow_bootstrap_token=False)
    assert desktop is not None
    assert desktop.enabled
    assert desktop.api_token == ""
    scripts = load_cloud_config(allow_bootstrap_token=True)
    assert scripts is not None
    assert scripts.api_token == "not-a-jwt"
