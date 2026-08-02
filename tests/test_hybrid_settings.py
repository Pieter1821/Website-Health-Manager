"""Local secret settings must not be overwritten by cloud values."""

from __future__ import annotations

from whm.infrastructure.hybrid_settings import HybridSettingsRepository


class MemSettings:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data = dict(initial or {})

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def get_all(self) -> dict[str, str]:
        return dict(self._data)


def test_secrets_stay_local() -> None:
    cloud = MemSettings({"timeout_seconds": "20", "smtp_password": "LEAK"})
    local = MemSettings({"smtp_password": "local-secret", "slack_webhook": "https://hooks.local"})
    hybrid = HybridSettingsRepository(cloud, local)  # type: ignore[arg-type]

    assert hybrid.get("timeout_seconds") == "20"
    assert hybrid.get("smtp_password") == "local-secret"
    hybrid.set("smtp_password", "new-local")
    hybrid.set("timeout_seconds", "30")
    assert local.get("smtp_password") == "new-local"
    assert "smtp_password" not in cloud.get_all() or cloud.get("smtp_password") == "LEAK"
    assert cloud.get("timeout_seconds") == "30"
    all_settings = hybrid.get_all()
    assert all_settings["smtp_password"] == "new-local"
    assert all_settings["slack_webhook"] == "https://hooks.local"
    assert all_settings["timeout_seconds"] == "30"
