"""Local HTTP API + static file server for the desktop web UI."""

from __future__ import annotations

import json
import logging
import mimetypes
import sqlite3
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.domain.models import FindingStatus, HealthCheckResult, Website
from whm.infrastructure.reports import build_report_bundle
from whm.presentation.copy import (
    category_plain,
    category_tip,
    finding_plain,
    overall_summary,
    risk_plain,
    status_plain,
)
logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent / "web"

SETTINGS_FIELDS = [
    ("timeout_seconds", "Wait time (seconds)", "Increase if internet is slow."),
    ("dns_server", "DNS server (optional)", "Leave blank for system DNS."),
    ("check_interval", "Automatic checks", "manual | hourly | every_6_hours | daily | weekly"),
    ("notify_on", "When to alert", "critical | warning | always | never"),
    ("notify_desktop", "Desktop alerts", "1 = yes, 0 = no"),
    ("export_folder", "Report folder", ""),
    ("slack_webhook", "Slack webhook", ""),
    ("discord_webhook", "Discord webhook", ""),
    ("teams_webhook", "Teams webhook", ""),
    ("generic_webhook", "Generic webhook", ""),
    ("smtp_host", "SMTP host", ""),
    ("smtp_port", "SMTP port", ""),
    ("smtp_username", "SMTP username", ""),
    ("smtp_password", "SMTP password", ""),
    ("mail_from", "From email", ""),
    ("mail_to", "To email", ""),
]


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


def serialize_site_row(site: Website, latest: Optional[HealthCheckResult]) -> dict[str, Any]:
    if latest is None:
        return {
            "id": site.id,
            "display_name": site.display_name,
            "domain": site.domain,
            "url": site.url,
            "overall": "unknown",
            "overall_label": "Not checked yet",
            "website_label": "—",
            "website_status": "unknown",
            "ssl_label": "—",
            "ssl_status": "unknown",
            "ssl_expires": "—",
            "ssl_expires_days": "",
            "domain_label": "—",
            "domain_status": "unknown",
            "domain_expires": "—",
            "domain_expires_days": "",
            "dns_label": "—",
            "dns_status": "unknown",
            "email_label": "—",
            "email_status": "unknown",
            "risk_label": "—",
            "last_checked_label": "Never",
            "response_ms": "—",
        }
    ssl_raw = (latest.raw or {}).get("ssl") or {}
    whois_raw = (latest.raw or {}).get("whois") or {}
    ssl_expires, ssl_days = _expiry_bits(
        ssl_raw.get("not_after"), ssl_raw.get("days_remaining")
    )
    domain_expires, domain_days = _expiry_bits(
        whois_raw.get("expiration_date"), whois_raw.get("days_remaining")
    )
    return {
        "id": site.id,
        "display_name": site.display_name,
        "domain": site.domain,
        "url": site.url,
        "overall": latest.overall_status.value,
        "overall_label": status_plain(latest.overall_status),
        "website_label": status_plain(latest.website_status),
        "website_status": latest.website_status.value,
        "ssl_label": status_plain(latest.ssl_status),
        "ssl_status": latest.ssl_status.value,
        "ssl_expires": ssl_expires,
        "ssl_expires_days": ssl_days,
        "domain_label": status_plain(latest.domain_status),
        "domain_status": latest.domain_status.value,
        "domain_expires": domain_expires,
        "domain_expires_days": domain_days,
        "dns_label": status_plain(latest.dns_status),
        "dns_status": latest.dns_status.value,
        "email_label": status_plain(latest.email_status),
        "email_status": latest.email_status.value,
        "risk_label": risk_plain(latest.risk_level),
        "last_checked_label": latest.checked_at.strftime("%Y-%m-%d %H:%M"),
        "response_ms": (
            f"{latest.response_time_ms:.0f}"
            if latest.response_time_ms is not None
            else "—"
        ),
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

    pills = [
        {"label": "Overall", "value": status_plain(latest.overall_status), "status": latest.overall_status.value},
        {"label": "Website", "value": status_plain(latest.website_status), "status": latest.website_status.value},
        {"label": "Certificate", "value": status_plain(latest.ssl_status), "status": latest.ssl_status.value},
        {"label": "Domain", "value": status_plain(latest.domain_status), "status": latest.domain_status.value},
        {"label": "DNS", "value": status_plain(latest.dns_status), "status": latest.dns_status.value},
        {"label": "Email", "value": status_plain(latest.email_status), "status": latest.email_status.value},
        {"label": "Risk", "value": risk_plain(latest.risk_level), "status": latest.overall_status.value},
    ]

    # Problems tab: only actionable items. Skip OK/info and security/speed noise.
    problem_statuses = {
        FindingStatus.INCORRECT,
        FindingStatus.MISSING,
        FindingStatus.INCONCLUSIVE,
    }
    ignored_categories = {"security", "performance"}
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
        "<th>Status <button type='button' class='info-btn' data-tip='Missing or needs fixing means you should act. Couldn’t check means your network blocked the test.' aria-label='About Status'>i</button></th>"
        "<th>Problem <button type='button' class='info-btn' data-tip='What is wrong, in plain words.' aria-label='About Problem'>i</button></th>"
        "<th>Fix <button type='button' class='info-btn' data-tip='The next step to put it right.' aria-label='About Fix'>i</button></th>"
        "</tr></thead>"
        f"<tbody>{''.join(finding_rows)}</tbody></table></div>"
        if finding_rows
        else "<p class='ok-banner'>No problems found — everything checked looks fine.</p>"
    )

    hist_rows = []
    for item in history:
        ms = f"{item.response_time_ms:.0f}" if item.response_time_ms is not None else "—"
        hist_rows.append(
            "<tr>"
            f"<td>{item.checked_at.strftime('%Y-%m-%d %H:%M:%S')}</td>"
            f"<td><span class='pill {item.overall_status.value}'>{_escape(status_plain(item.overall_status))}</span></td>"
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
        "summary": overall_summary(latest.overall_status, site.display_name),
        "overall": latest.overall_status.value,
        "overall_label": status_plain(latest.overall_status),
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
    ) -> None:
        self.websites = websites
        self.scans = scans
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()


def make_handler(ctx: AppContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "WHM/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("HTTP " + fmt, *args)

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
                rows = [
                    serialize_site_row(site, ctx.scans.latest(site.id) if site.id else None)
                    for site in ctx.websites.list_websites()
                ]
                self._send(*_json_bytes({"sites": rows}))
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
                        "hint": hint,
                        "value": values.get(key, ""),
                        "type": "password" if "password" in key else "text",
                    }
                    for key, label, hint in SETTINGS_FIELDS
                ]
                self._send(*_json_bytes({"fields": fields}))
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

            if path == "/api/sites":
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

            if path == "/api/import":
                filename = str(payload.get("filename", "")).strip() or "import.csv"
                content_b64 = str(payload.get("content_base64", "")).strip()
                if not content_b64:
                    self._send(*_json_bytes({"error": "No file content received"}, 400))
                    return
                import base64

                try:
                    raw = base64.b64decode(content_b64)
                except Exception:  # noqa: BLE001
                    self._send(*_json_bytes({"error": "Could not read the uploaded file"}, 400))
                    return
                try:
                    result = ctx.websites.import_list(filename, raw)
                except Exception as exc:  # noqa: BLE001
                    self._send(*_json_bytes({"error": str(exc)}, 400))
                    return
                self._send(
                    *_json_bytes(
                        {
                            "summary": result.summary,
                            "added": result.added,
                            "skipped": result.skipped,
                            "errors": result.errors,
                            "added_count": len(result.added),
                            "skipped_count": len(result.skipped),
                            "error_count": len(result.errors),
                        }
                    )
                )
                return

            if path.endswith("/scan") and path.startswith("/api/sites/"):
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
                                "message": "Check failed",
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
                filename, payload = build_report_bundle(site, latest)
                self._send(
                    200,
                    payload,
                    "application/zip",
                    download_name=filename,
                )
                return

            self._send(*_json_bytes({"error": "Not found"}, 404))

        def do_PUT(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/settings":
                self._send(*_json_bytes({"error": "Not found"}, 404))
                return
            payload = self._read_json()
            for key, value in payload.items():
                ctx.settings.set(str(key), str(value))
            self._send(*_json_bytes({"ok": True}))

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if not path.startswith("/api/sites/"):
                self._send(*_json_bytes({"error": "Not found"}, 404))
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
) -> tuple[ThreadingHTTPServer, str]:
    """Start the local UI server. Prefers a stable port so refresh keeps working."""
    ctx = AppContext(websites, scans, settings)
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
