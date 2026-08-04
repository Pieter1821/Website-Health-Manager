"""Local HTTP API + static file server for the desktop web UI."""

from __future__ import annotations

import json
import logging
import mimetypes
import sqlite3
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from datetime import datetime, timedelta, timezone

from whm import __version__ as APP_VERSION
from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.domain.models import FindingStatus, HealthCheckResult, Website
from whm.domain.status import display_overall, status_to_risk
from whm.infrastructure.cloud_client import CloudApiClient, CloudApiError
from whm.infrastructure.cloud_config import (
    clear_cloud_session,
    is_session_jwt,
    load_cloud_config,
    save_cloud_config,
)
from whm.infrastructure.reports import (
    save_portfolio_report_to_downloads,
    save_report_to_downloads,
)
from whm.infrastructure.updates import check_for_update, update_info_dict
from whm.presentation.copy import (
    category_plain,
    category_tip,
    finding_plain,
    overall_summary,
    overall_why,
    risk_plain,
    status_plain,
    website_plain,
)
from whm.presentation.settings_fields import SETTINGS_FIELDS

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent / "web"


def _json_bytes(payload: Any, status: int = 200) -> tuple[int, bytes, str]:
    return status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _expiry_bits(iso_date: Any, days_remaining: Any) -> tuple[str, str]:
    """Return (date_label, days_label) for table cells."""
    date_label = "—"
    days_label = ""
    if isinstance(iso_date, str) and iso_date:
        date_label = iso_date[:10]  # YYYY-MM-DD
    if isinstance(days_remaining, (int, float)):
        days = int(days_remaining)
        if days < 0:
            days_label = f"Expired {abs(days)} days ago"
        elif days == 0:
            days_label = "Expires today"
        else:
            days_label = f"{days} days left"
    return date_label, days_label


def serialize_site_row(
    site: Website,
    latest: Optional[HealthCheckResult],
    *,
    customer_name: str = "",
) -> dict[str, Any]:
    base = {
        "id": site.id,
        "display_name": site.display_name,
        "domain": site.domain,
        "url": site.url,
        "customer_id": site.customer_id,
        "customer_name": customer_name or "",
    }
    if latest is None:
        return {
            **base,
            "overall": "unknown",
            "overall_label": "Not checked yet",
            "overall_why": "Run Check to see the details",
            "website_label": "—",
            "website_status": "unknown",
            "ssl_label": "—",
            "ssl_status": "unknown",
            "ssl_expires": "—",
            "ssl_expires_days": "",
            "ssl_expires_days_num": None,
            "domain_label": "—",
            "domain_status": "unknown",
            "domain_expires": "—",
            "domain_expires_days": "",
            "domain_expires_days_num": None,
            "dns_label": "—",
            "dns_status": "unknown",
            "risk_label": "—",
            "last_checked_label": "Never",
            "last_checked_at": None,
            "response_ms": "—",
            "check_failed": False,
        }
    ssl_raw = (latest.raw or {}).get("ssl") or {}
    whois_raw = (latest.raw or {}).get("whois") or {}
    website_raw = (latest.raw or {}).get("website") or {}
    ssl_expires, ssl_days = _expiry_bits(
        ssl_raw.get("not_after"), ssl_raw.get("days_remaining")
    )
    domain_expires, domain_days = _expiry_bits(
        whois_raw.get("expiration_date"), whois_raw.get("days_remaining")
    )
    overall = display_overall(latest)
    probe_failed = bool(website_raw.get("probe_failed"))
    check_failed = bool(
        probe_failed
        or (latest.error_message or "").strip()
        or website_raw.get("error")
    )
    return {
        **base,
        "overall": overall.value,
        "overall_label": status_plain(overall),
        "overall_why": overall_why(latest),
        "website_label": website_plain(
            latest.website_status, probe_failed=probe_failed
        ),
        "website_status": latest.website_status.value,
        "ssl_label": status_plain(latest.ssl_status),
        "ssl_status": latest.ssl_status.value,
        "ssl_expires": ssl_expires,
        "ssl_expires_days": ssl_days,
        "ssl_expires_days_num": ssl_raw.get("days_remaining"),
        "domain_label": status_plain(latest.domain_status),
        "domain_status": latest.domain_status.value,
        "domain_expires": domain_expires,
        "domain_expires_days": domain_days,
        "domain_expires_days_num": whois_raw.get("days_remaining"),
        "dns_label": status_plain(latest.dns_status),
        "dns_status": latest.dns_status.value,
        "risk_label": risk_plain(status_to_risk(overall)),
        "last_checked_label": latest.checked_at.strftime("%Y-%m-%d %H:%M"),
        "last_checked_at": latest.checked_at.isoformat(),
        "response_ms": (
            f"{latest.response_time_ms:.0f}"
            if latest.response_time_ms is not None
            else "—"
        ),
        "check_failed": check_failed,
    }


def serialize_detail(
    site: Website,
    latest: Optional[HealthCheckResult],
    history: list[HealthCheckResult],
    changes: list[dict[str, str]],
) -> dict[str, Any]:
    if latest is None:
        empty_table = "<p class='muted'>No results yet.</p>"
        return {
            "id": site.id,
            "display_name": site.display_name,
            "domain": site.domain,
            "summary": "Not checked yet — press Check again.",
            "overall_label": "Not checked yet",
            "pills": [],
            "findings_html": empty_table,
            "history_html": empty_table,
            "changes_html": empty_table,
        }

    overall = display_overall(latest)
    pills = [
        {"label": "Overall", "value": status_plain(overall), "status": overall.value},
        {"label": "Website", "value": status_plain(latest.website_status), "status": latest.website_status.value},
        {"label": "Certificate", "value": status_plain(latest.ssl_status), "status": latest.ssl_status.value},
        {"label": "Domain", "value": status_plain(latest.domain_status), "status": latest.domain_status.value},
        {"label": "DNS", "value": status_plain(latest.dns_status), "status": latest.dns_status.value},
        {"label": "Risk", "value": risk_plain(status_to_risk(overall)), "status": overall.value},
    ]

    # Problems tab: only actionable items. Skip OK/info and security/speed noise.
    # Email auth findings are omitted — they clutter website monitoring.
    problem_statuses = {
        FindingStatus.INCORRECT,
        FindingStatus.MISSING,
        FindingStatus.INCONCLUSIVE,
    }
    ignored_categories = {
        "security",
        "performance",
        "smtp",
        "spf",
        "dkim",
        "dmarc",
        "mx",
        "sendgrid",
    }
    finding_rows: list[str] = []
    for finding in latest.findings:
        if finding.category in ignored_categories:
            continue
        if finding.status not in problem_statuses:
            continue
        status_cls = (
            "unknown" if finding.status.value == "inconclusive" else finding.status.value
        )
        action = (finding.recommendation or "").strip()
        # Drop vague "ask a developer" style copy — keep only concrete next steps.
        if "developer" in action.lower():
            action = ""
        tip = _escape(category_tip(finding.category))
        finding_rows.append(
            "<tr>"
            f"<td>{_escape(category_plain(finding.category))} "
            f"<button type='button' class='info-btn' data-tip='{tip}' "
            f"aria-label='About {_escape(category_plain(finding.category))}'>i</button></td>"
            f"<td><span class='pill {status_cls}'>{_escape(finding_plain(finding.status))}</span></td>"
            f"<td><strong>{_escape(finding.title)}</strong>"
            f"<div class='cell-sub'>{_escape(finding.message)}</div></td>"
            f"<td class='action-cell'>{_escape(action) if action else '—'}</td>"
            "</tr>"
        )
    findings_html = (
        "<div class='table-wrap'><table class='data-table findings-table'>"
        "<thead><tr>"
        "<th>Area <button type='button' class='info-btn' data-tip='Which part of the site this problem is about.' aria-label='About Area'>i</button></th>"
        "<th>Status <button type='button' class='info-btn' data-tip='Review or Not set up means there is something to improve. Couldn’t finish means the check did not complete — try again.' aria-label='About Status'>i</button></th>"
        "<th>Problem <button type='button' class='info-btn' data-tip='What we found, in plain words.' aria-label='About Problem'>i</button></th>"
        "<th>Fix <button type='button' class='info-btn' data-tip='A practical next step.' aria-label='About Fix'>i</button></th>"
        "</tr></thead>"
        f"<tbody>{''.join(finding_rows)}</tbody></table></div>"
        if finding_rows
        else "<p class='ok-banner'>No problems found — everything checked looks fine.</p>"
    )

    hist_rows = []
    for item in history:
        ms = f"{item.response_time_ms:.0f}" if item.response_time_ms is not None else "—"
        # Recompute — older rows may have stored overall from email checks.
        hist_overall = display_overall(item)
        hist_rows.append(
            "<tr>"
            f"<td>{item.checked_at.strftime('%Y-%m-%d %H:%M:%S')}</td>"
            f"<td><span class='pill {hist_overall.value}'>{_escape(status_plain(hist_overall))}</span></td>"
            f"<td>{ms}</td>"
            "</tr>"
        )
    history_html = (
        "<div class='table-wrap'><table class='data-table'>"
        "<thead><tr><th>When</th><th>Overall</th><th>Response ms</th></tr></thead>"
        f"<tbody>{''.join(hist_rows)}</tbody></table></div>"
        if hist_rows
        else "<p class='muted'>No history yet.</p>"
    )

    if changes:
        change_rows = [
            "<tr>"
            f"<td>{_escape(c['change'].title())}</td>"
            f"<td>{_escape(c['rtype'])}</td>"
            f"<td>{_escape(c['old_value'] or '—')}</td>"
            f"<td>{_escape(c['new_value'] or '—')}</td>"
            "</tr>"
            for c in changes
        ]
        changes_html = (
            "<div class='table-wrap'><table class='data-table'>"
            "<thead><tr><th>Change</th><th>Type</th><th>Old value</th><th>New value</th></tr></thead>"
            f"<tbody>{''.join(change_rows)}</tbody></table></div>"
        )
    else:
        changes_html = (
            "<p class='muted'>No address-setting changes between the last two successful checks.</p>"
        )

    return {
        "id": site.id,
        "display_name": site.display_name,
        "domain": site.domain,
        "summary": overall_summary(overall, site.display_name),
        "overall": overall.value,
        "overall_label": status_plain(overall),
        "overall_why": overall_why(latest),
        "pills": pills,
        "findings_html": findings_html,
        "history_html": history_html,
        "changes_html": changes_html,
    }


class AppContext:
    def __init__(
        self,
        websites: WebsiteService,
        scans: HealthScanService,
        settings: SettingsService,
        cloud_client: CloudApiClient | None = None,
    ) -> None:
        self.websites = websites
        self.scans = scans
        self.settings = settings
        self.cloud = cloud_client
        self.auth_user: dict[str, Any] | None = None
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        if cloud_client:
            if cloud_client.token and is_session_jwt(cloud_client.token):
                try:
                    me = cloud_client.me()
                    self.auth_user = me.get("user") if isinstance(me, dict) else None
                except CloudApiError:
                    self.auth_user = None
            else:
                self.auth_user = None

    @property
    def cloud_mode(self) -> bool:
        return self.cloud is not None

    @property
    def role(self) -> str:
        if self.auth_user and self.auth_user.get("role"):
            return str(self.auth_user["role"])
        cfg = load_cloud_config(allow_bootstrap_token=False)
        return (cfg.role if cfg else "") or ""

    def require_cloud_roles(self, *roles: str) -> tuple[int, bytes, str] | None:
        if not self.cloud_mode:
            return None
        if not self.auth_user:
            return _json_bytes({"error": "Sign in required", "auth_required": True}, 401)
        if self.role not in roles:
            return _json_bytes(
                {"error": "You do not have permission for this action"}, 403
            )
        return None


def make_handler(ctx: AppContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "WHM/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("HTTP " + fmt, *args)

        def _apply_session(self, data: dict[str, Any]) -> None:
            token = str(data.get("token") or "")
            user = data.get("user") or {}
            expires_in = int(data.get("expires_in") or 12 * 60 * 60)
            if not ctx.cloud or not token:
                return
            ctx.cloud.set_token(token)
            ctx.auth_user = user if isinstance(user, dict) else None
            expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            save_cloud_config(
                ctx.cloud.api_url,
                token,
                username=str(user.get("username") or ""),
                session_expires_at=expires.isoformat().replace("+00:00", "Z"),
                role=str(user.get("role") or ""),
            )

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            *,
            download_name: str | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if download_name:
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{download_name}"',
                )
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path in {"/", "/index.html"}:
                data = (WEB_ROOT / "index.html").read_bytes()
                self._send(200, data, "text/html; charset=utf-8")
                return
            if path.startswith("/static/"):
                name = path.removeprefix("/static/")
                file_path = WEB_ROOT / name
                if not file_path.exists() or not file_path.is_file():
                    self._send(404, b"missing", "text/plain")
                    return
                ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                self._send(200, file_path.read_bytes(), ctype)
                return

            if path == "/api/sites":
                if ctx.cloud_mode and not ctx.auth_user:
                    self._send(
                        *_json_bytes(
                            {"error": "Sign in required", "auth_required": True}, 401
                        )
                    )
                    return
                if ctx.cloud_mode and not ctx.cloud:
                    self._send(
                        *_json_bytes(
                            {"error": "Cloud not configured", "auth_required": False}, 401
                        )
                    )
                    return
                # Drop leftover customer names that no longer have any sites.
                try:
                    ctx.websites.purge_unused_customers()
                except Exception:  # noqa: BLE001
                    logger.debug("Could not purge unused customers", exc_info=True)
                customers = {
                    c.id: c.name
                    for c in ctx.websites.list_customers()
                    if c.id is not None
                }
                sites = ctx.websites.list_websites()
                rows = [
                    serialize_site_row(
                        site,
                        ctx.scans.latest(site.id) if site.id else None,
                        customer_name=customers.get(site.customer_id or -1, ""),
                    )
                    for site in sites
                ]
                used_ids = {
                    site.customer_id
                    for site in sites
                    if site.customer_id is not None
                }
                self._send(
                    *_json_bytes(
                        {
                            "sites": rows,
                            "customers": [
                                {"id": cid, "name": customers[cid]}
                                for cid in sorted(
                                    used_ids,
                                    key=lambda i: customers.get(i, "").lower(),
                                )
                                if cid in customers
                            ],
                        }
                    )
                )
                return

            if path.startswith("/api/sites/") and path.count("/") == 3:
                site_id = int(path.rsplit("/", 1)[-1])
                site = ctx.websites.get_website(site_id)
                if site is None:
                    self._send(*_json_bytes({"error": "Website not found"}, 404))
                    return
                latest = ctx.scans.latest(site_id)
                detail = serialize_detail(
                    site,
                    latest,
                    ctx.scans.history(site_id),
                    ctx.scans.dns_diff(site_id),
                )
                self._send(*_json_bytes(detail))
                return

            if path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                with ctx._lock:
                    job = ctx.jobs.get(job_id)
                if not job:
                    self._send(*_json_bytes({"error": "Job not found"}, 404))
                    return
                self._send(*_json_bytes(job))
                return

            if path == "/api/settings":
                values = ctx.settings.get_all()
                fields = [
                    {
                        "key": key,
                        "label": label,
                        "tip": tip,
                        "hint": hint,
                        "value": values.get(key, ""),
                        "type": "password" if "password" in key else "text",
                    }
                    for key, label, tip, hint in SETTINGS_FIELDS
                ]
                self._send(*_json_bytes({"fields": fields}))
                return

            if path == "/api/version":
                self._send(
                    *_json_bytes(
                        {
                            "version": APP_VERSION,
                            "app": "Website Health Manager",
                        }
                    )
                )
                return

            if path == "/api/updates/check":
                info = check_for_update()
                self._send(*_json_bytes(update_info_dict(info)))
                return

            if path == "/api/auth/status":
                cfg = load_cloud_config(allow_bootstrap_token=False)
                cloud_mode = ctx.cloud is not None
                authed = bool(ctx.auth_user) if cloud_mode else True
                self._send(
                    *_json_bytes(
                        {
                            "cloud_mode": cloud_mode,
                            "authenticated": authed,
                            "api_url": (cfg.api_url if cfg else "") or (
                                ctx.cloud.api_url if ctx.cloud else ""
                            ),
                            "username": (ctx.auth_user or {}).get("username")
                            or (cfg.username if cfg else ""),
                            "role": ctx.role if cloud_mode else "admin",
                            "user": ctx.auth_user,
                        }
                    )
                )
                return

            if path == "/api/users":
                denied = ctx.require_cloud_roles("admin")
                if denied:
                    self._send(*denied)
                    return
                assert ctx.cloud is not None
                try:
                    data = ctx.cloud.list_users()
                except CloudApiError as exc:
                    self._send(*_json_bytes({"error": str(exc)}, exc.status_code or 400))
                    return
                self._send(*_json_bytes(data))
                return

            self._send(*_json_bytes({"error": "Not found"}, 404))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                payload = self._read_json()
            except json.JSONDecodeError:
                self._send(*_json_bytes({"error": "Invalid JSON"}, 400))
                return

            if path == "/api/auth/login":
                if not ctx.cloud:
                    self._send(*_json_bytes({"error": "Cloud mode is not enabled"}, 400))
                    return
                email = str(payload.get("email") or payload.get("username") or "").strip()
                password = str(payload.get("password", ""))
                try:
                    data = ctx.cloud.login(email, password)
                except CloudApiError as exc:
                    self._send(*_json_bytes({"error": str(exc)}, exc.status_code or 401))
                    return
                if data.get("status") == "ok" and data.get("token"):
                    self._apply_session(data)
                    self._send(
                        *_json_bytes({"status": "ok", "user": data.get("user")})
                    )
                    return
                self._send(*_json_bytes(data))
                return

            if path == "/api/auth/logout":
                if ctx.cloud:
                    ctx.cloud.set_token("")
                ctx.auth_user = None
                clear_cloud_session()
                self._send(*_json_bytes({"ok": True}))
                return

            if path == "/api/users":
                denied = ctx.require_cloud_roles("admin")
                if denied:
                    self._send(*denied)
                    return
                assert ctx.cloud is not None
                try:
                    data = ctx.cloud.create_user(
                        str(payload.get("email") or payload.get("username") or "").strip(),
                        str(payload.get("password", "")),
                        str(payload.get("role", "operator")),
                    )
                except CloudApiError as exc:
                    self._send(*_json_bytes({"error": str(exc)}, exc.status_code or 400))
                    return
                self._send(*_json_bytes(data))
                return

            if path == "/api/sites":
                denied = ctx.require_cloud_roles("admin", "operator")
                if denied:
                    self._send(*denied)
                    return
                url = str(payload.get("url", "")).strip()
                if not url:
                    self._send(*_json_bytes({"error": "Type a website first"}, 400))
                    return
                try:
                    customer_id = None
                    customer = str(payload.get("customer", "")).strip()
                    if customer:
                        customer_id = ctx.websites.add_customer(customer).id
                    site = ctx.websites.add_website(url=url, customer_id=customer_id)
                except ValueError as exc:
                    self._send(*_json_bytes({"error": str(exc)}, 400))
                    return
                except sqlite3.IntegrityError:
                    logger.exception("Could not save website")
                    self._send(
                        *_json_bytes(
                            {
                                "error": (
                                    "Could not save that website. "
                                    "Try again with just the address, like mybusiness.co.za"
                                )
                            },
                            400,
                        )
                    )
                    return
                self._send(*_json_bytes({"id": site.id, "domain": site.domain}))
                return

            if path == "/api/sites/clear-all":
                denied = ctx.require_cloud_roles("admin")
                if denied:
                    self._send(*denied)
                    return
                if str(payload.get("confirm", "")).strip() != "remove-all":
                    self._send(
                        *_json_bytes(
                            {
                                "error": 'Send {"confirm":"remove-all"} to remove every website'
                            },
                            400,
                        )
                    )
                    return
                removed = ctx.websites.delete_all_websites()
                self._send(*_json_bytes({"ok": True, "removed": removed}))
                return

            if path == "/api/updates/open":
                url = str(payload.get("url", "")).strip()
                if not url.startswith("https://"):
                    self._send(
                        *_json_bytes({"error": "Only https download links are allowed"}, 400)
                    )
                    return
                allowed_hosts = (
                    "github.com",
                    "objects.githubusercontent.com",
                    "release-assets.githubusercontent.com",
                )
                host = (urlparse(url).hostname or "").lower()
                if host not in allowed_hosts and not host.endswith(".githubusercontent.com"):
                    self._send(
                        *_json_bytes({"error": "Download host is not allowed"}, 400)
                    )
                    return
                webbrowser.open(url)
                self._send(*_json_bytes({"ok": True}))
                return

            if path == "/api/export-all":
                sites = ctx.websites.list_websites()
                if not sites:
                    self._send(
                        *_json_bytes(
                            {"error": "No websites yet — import a list or check one first"},
                            400,
                        )
                    )
                    return
                fmt = str(payload.get("format", "excel") or "excel").strip().lower()
                rows = [
                    (site, ctx.scans.latest(site.id) if site.id else None)
                    for site in sites
                ]
                try:
                    saved = save_portfolio_report_to_downloads(rows, format=fmt)
                except OSError as exc:
                    self._send(
                        *_json_bytes(
                            {"error": f"Could not save to Downloads: {exc}"},
                            500,
                        )
                    )
                    return
                self._send(
                    *_json_bytes(
                        {
                            "ok": True,
                            "format": "csv" if fmt == "csv" else "excel",
                            "filename": saved.name,
                            "path": str(saved),
                            "folder": str(saved.parent),
                            "site_count": len(sites),
                        }
                    )
                )
                return

            if path == "/api/import":
                denied = ctx.require_cloud_roles("admin", "operator")
                if denied:
                    self._send(*denied)
                    return
                filename = str(payload.get("filename", "")).strip() or "import.csv"
                content_b64 = str(payload.get("content_base64", "")).strip()
                if not content_b64:
                    self._send(
                        *_json_bytes(
                            {
                                "error": (
                                    "No file was received. Choose an Excel (.xlsx) "
                                    "or CSV file and try again."
                                )
                            },
                            400,
                        )
                    )
                    return
                import base64

                from whm.infrastructure.importer import friendly_parse_error

                try:
                    raw = base64.b64decode(content_b64)
                except Exception:  # noqa: BLE001
                    self._send(
                        *_json_bytes(
                            {
                                "error": (
                                    f"Couldn’t read “{filename}”. "
                                    "Try saving it again as .xlsx or CSV, then import."
                                )
                            },
                            400,
                        )
                    )
                    return
                if not raw:
                    self._send(
                        *_json_bytes(
                            {
                                "error": (
                                    f"“{filename}” looks empty. "
                                    "Add website addresses and save, then import again."
                                )
                            },
                            400,
                        )
                    )
                    return
                try:
                    result = ctx.websites.import_list(filename, raw)
                except Exception as exc:  # noqa: BLE001
                    self._send(
                        *_json_bytes(
                            {"error": friendly_parse_error(exc, filename)},
                            400,
                        )
                    )
                    return
                self._send(*_json_bytes(result.as_api_dict()))
                return

            if path.endswith("/scan") and path.startswith("/api/sites/"):
                denied = ctx.require_cloud_roles("admin", "operator")
                if denied:
                    self._send(*denied)
                    return
                site_id = int(path.split("/")[3])
                site = ctx.websites.get_website(site_id)
                if site is None:
                    self._send(*_json_bytes({"error": "Website not found"}, 404))
                    return
                job_id = uuid.uuid4().hex
                with ctx._lock:
                    ctx.jobs[job_id] = {"status": "running", "message": "Starting…"}

                def worker() -> None:
                    try:
                        def progress(message: str) -> None:
                            with ctx._lock:
                                ctx.jobs[job_id]["message"] = message

                        result = ctx.scans.scan_website(site_id, progress=progress)
                        detail = serialize_detail(
                            site,
                            result,
                            ctx.scans.history(site_id),
                            ctx.scans.dns_diff(site_id),
                        )
                        with ctx._lock:
                            ctx.jobs[job_id] = {
                                "status": "done",
                                "message": "Done.",
                                "detail": detail,
                            }
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Scan job failed")
                        with ctx._lock:
                            ctx.jobs[job_id] = {
                                "status": "error",
                                "error": str(exc),
                                "message": "Check didn’t finish",
                            }

                threading.Thread(target=worker, daemon=True).start()
                self._send(*_json_bytes({"job_id": job_id}))
                return

            if path.endswith("/export") and path.startswith("/api/sites/"):
                site_id = int(path.split("/")[3])
                site = ctx.websites.get_website(site_id)
                latest = ctx.scans.latest(site_id)
                if site is None or latest is None:
                    self._send(*_json_bytes({"error": "Nothing to download yet — run Check first"}, 400))
                    return
                fmt = (
                    parse_qs(urlparse(self.path).query).get("format", ["excel"])[0]
                    or "excel"
                ).strip().lower()
                try:
                    saved = save_report_to_downloads(site, latest, format=fmt)
                except OSError as exc:
                    self._send(
                        *_json_bytes(
                            {"error": f"Could not save to Downloads: {exc}"},
                            500,
                        )
                    )
                    return
                self._send(
                    *_json_bytes(
                        {
                            "ok": True,
                            "format": "csv" if fmt == "csv" else "excel",
                            "filename": saved.name,
                            "path": str(saved),
                            "folder": str(saved.parent),
                        }
                    )
                )
                return

            self._send(*_json_bytes({"error": "Not found"}, 404))

        def do_PUT(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/users/"):
                denied = ctx.require_cloud_roles("admin")
                if denied:
                    self._send(*denied)
                    return
                assert ctx.cloud is not None
                user_id = int(path.rsplit("/", 1)[-1])
                payload = self._read_json()
                try:
                    data = ctx.cloud.patch_user(user_id, payload)
                except CloudApiError as exc:
                    self._send(*_json_bytes({"error": str(exc)}, exc.status_code or 400))
                    return
                self._send(*_json_bytes(data))
                return
            if path != "/api/settings":
                self._send(*_json_bytes({"error": "Not found"}, 404))
                return
            denied = ctx.require_cloud_roles("admin")
            if denied:
                self._send(*denied)
                return
            payload = self._read_json()
            for key, value in payload.items():
                ctx.settings.set(str(key), str(value))
            self._send(*_json_bytes({"ok": True}))

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/users/"):
                denied = ctx.require_cloud_roles("admin")
                if denied:
                    self._send(*denied)
                    return
                assert ctx.cloud is not None
                user_id = int(path.rsplit("/", 1)[-1])
                try:
                    data = ctx.cloud.delete_user(user_id)
                except CloudApiError as exc:
                    self._send(*_json_bytes({"error": str(exc)}, exc.status_code or 400))
                    return
                self._send(*_json_bytes(data))
                return
            if not path.startswith("/api/sites/"):
                self._send(*_json_bytes({"error": "Not found"}, 404))
                return
            denied = ctx.require_cloud_roles("admin")
            if denied:
                self._send(*denied)
                return
            site_id = int(path.rsplit("/", 1)[-1])
            ctx.websites.delete_website(site_id)
            self._send(*_json_bytes({"ok": True}))

    return Handler


def start_server(
    websites: WebsiteService,
    scans: HealthScanService,
    settings: SettingsService,
    host: str = "127.0.0.1",
    port: int = 17865,
    cloud_client: CloudApiClient | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Start the local UI server. Prefers a stable port so refresh keeps working."""
    ctx = AppContext(websites, scans, settings, cloud_client=cloud_client)
    handler = make_handler(ctx)
    tried: list[int] = [port, 17866, 17867, 0]
    server: ThreadingHTTPServer | None = None
    last_error: Exception | None = None
    for candidate in tried:
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError as exc:
            last_error = exc
            continue
    if server is None:
        raise RuntimeError(f"Could not start UI server: {last_error}")
    chosen = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="whm-http", daemon=True)
    thread.start()
    url = f"http://{host}:{chosen}/"
    logger.info("WHM UI server at %s", url)
    return server, url
