"""Merge cloud (non-secret) settings with local-only secret settings."""

from __future__ import annotations

from whm.domain.ports import SettingsRepository
from whm.infrastructure.secret_settings import SECRET_SETTING_KEYS


class HybridSettingsRepository(SettingsRepository):
    def __init__(
        self,
        cloud: SettingsRepository,
        local: SettingsRepository,
    ) -> None:
        self._cloud = cloud
        self._local = local

    def get(self, key: str, default: str = "") -> str:
        if key in SECRET_SETTING_KEYS:
            return self._local.get(key, default)
        value = self._cloud.get(key, "")
        if value != "":
            return value
        return self._local.get(key, default)

    def set(self, key: str, value: str) -> None:
        if key in SECRET_SETTING_KEYS:
            self._local.set(key, value)
            return
        self._cloud.set(key, value)

    def get_all(self) -> dict[str, str]:
        merged = {
            k: v
            for k, v in self._cloud.get_all().items()
            if k not in SECRET_SETTING_KEYS
        }
        local_all = self._local.get_all()
        for key in SECRET_SETTING_KEYS:
            merged[key] = local_all.get(key, "")
        # Preserve any other local-only keys (e.g. theme) if cloud lacks them.
        for key, value in local_all.items():
            if key not in merged:
                merged[key] = value
        return merged
