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

    @property
    def api_url(self) -> str:
        return self._base

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str) -> None:
        self._token = (token or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {
            "X-WHM-Client": DESKTOP_CLIENT_HEADER,
            "User-Agent": "WebsiteHealthManager-Desktop/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Optional[dict[str, Any]] = None,
        auth: bool = True,
    ) -> Any:
        url = f"{self._base}{path}"
        headers = self._headers()
        if not auth:
            headers.pop("Authorization", None)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                res = client.request(
                    method,
                    url,
                    headers=headers,
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

    def post(self, path: str, body: Any = None, *, auth: bool = True) -> Any:
        return self.request("POST", path, json_body=body, auth=auth)

    def put(self, path: str, body: Any = None) -> Any:
        return self.request("PUT", path, json_body=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def login(self, email: str, password: str) -> dict[str, Any]:
        identity = (email or "").strip()
        return self.post(
            "/api/auth/login",
            {"email": identity, "username": identity, "password": password},
            auth=False,
        )

    def register(self, email: str, password: str) -> dict[str, Any]:
        identity = (email or "").strip()
        return self.post(
            "/api/auth/register",
            {"email": identity, "username": identity, "password": password},
            auth=False,
        )

    def bootstrap_admin(self, bootstrap_token: str, email: str, password: str) -> dict[str, Any]:
        previous = self._token
        self._token = bootstrap_token
        try:
            return self.post(
                "/api/auth/bootstrap",
                {"email": email, "username": email, "password": password},
            )
        finally:
            self._token = previous

    def me(self) -> dict[str, Any]:
        return self.get("/api/auth/me")

    def list_users(self) -> dict[str, Any]:
        return self.get("/api/users")

    def create_user(self, email: str, password: str, role: str) -> dict[str, Any]:
        identity = (email or "").strip()
        return self.post(
            "/api/users",
            {"email": identity, "username": identity, "password": password, "role": role},
        )

    def patch_user(self, user_id: int, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", f"/api/users/{user_id}", json_body=body)

    def delete_user(self, user_id: int) -> dict[str, Any]:
        return self.delete(f"/api/users/{user_id}")
