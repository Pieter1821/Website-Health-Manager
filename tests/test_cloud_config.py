"""Cloud connection config helpers."""

from __future__ import annotations

import json
from pathlib import Path

from whm.infrastructure.cloud_config import CloudConfig, load_cloud_config, save_cloud_config


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
