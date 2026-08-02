"""HTTPS client used by the WHM desktop app to talk to private D1 storage."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from whm.infrastructure.cloud_config import CloudConfig

# Identifies this process as the desktop app (Worker rejects other clients).
DESKTOP_CLIENT_HEADER = "desktop"


class CloudApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class CloudApiClient:
    def __init__(self, config: CloudConfig, timeout: float = 60.0) -> None:
        self._base = config.api_url.rstrip("/")
        self._token = config.api_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "X-WHM-Client": DESKTOP_CLIENT_HEADER,
            "User-Agent": "WebsiteHealthManager-Desktop/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self._base}{path}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                res = client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise CloudApiError(f"Cloud API unreachable: {exc}") from exc
        if res.status_code >= 400:
            try:
                detail = res.json().get("error") or res.text
            except Exception:  # noqa: BLE001
                detail = res.text
            raise CloudApiError(str(detail) or res.reason_phrase, res.status_code)
        if res.status_code == 204 or not res.content:
            return None
        return res.json()

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, json_body=body)

    def put(self, path: str, body: Any = None) -> Any:
        return self.request("PUT", path, json_body=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)
