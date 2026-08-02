"""HTTP API routes for the desktop UI (local server, no external network)."""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from whm.domain.models import (
    Finding,
    FindingStatus,
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
)
from whm.presentation.webapi import AppContext, _expiry_bits, make_handler
from tests.helpers import dns_with_records, healthy_check


@pytest.fixture
def api_server(website_service, scan_service, settings_service):
    ctx = AppContext(website_service, scan_service, settings_service)
    handler = make_handler(ctx)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, ctx, website_service, scan_service, settings_service
    server.shutdown()
    server.server_close()


def _request(base: str, method: str, path: str, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def test_expiry_bits():
    assert _expiry_bits("2026-09-01T12:00:00+00:00", 31) == ("2026-09-01", "31 days left")
    assert _expiry_bits("2026-01-01", 0)[1] == "Expires today"
    assert _expiry_bits("2026-01-01", -3)[1] == "Expired 3 days ago"
    assert _expiry_bits(None, None) == ("—", "")


def test_index_and_static(api_server):
    base, *_ = api_server
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        assert resp.status == 200
        assert b"Website Health Manager" in resp.read()
    with urllib.request.urlopen(base + "/static/app.js", timeout=5) as resp:
        assert resp.status == 200
        assert b"function" in resp.read()


def test_post_site_validation_and_create(api_server):
    base, _, websites, *_ = api_server
    status, body = _request(base, "POST", "/api/sites", {"url": ""})
    assert status == 400
    assert "website" in body["error"].lower()

    status, body = _request(
        base, "POST", "/api/sites", {"url": "mybiz.co.za", "customer": "Acme"}
    )
    assert status == 200
    assert body["domain"] == "mybiz.co.za"
    assert websites.get_website(body["id"]) is not None


def test_list_and_get_site(api_server):
    base, _, websites, scans, _ = api_server
    site = websites.add_website("https://example.com", display_name="Example")
    status, body = _request(base, "GET", "/api/sites")
    assert status == 200
    assert body["sites"][0]["overall_label"] == "Not checked yet"

    status, body = _request(base, "GET", f"/api/sites/{site.id}")
    assert status == 200
    assert body["display_name"] == "Example"

    status, body = _request(base, "GET", "/api/sites/99999")
    assert status == 404


def test_delete_site(api_server):
    base, _, websites, *_ = api_server
    site = websites.add_website("https://example.com")
    status, body = _request(base, "DELETE", f"/api/sites/{site.id}")
    assert status == 200
    assert body["ok"] is True
    assert websites.get_website(site.id) is None


def test_clear_all_sites(api_server):
    base, _, websites, *_ = api_server
    websites.add_website("https://one.example")
    websites.add_website("https://two.example")
    status, body = _request(base, "POST", "/api/sites/clear-all", {})
    assert status == 400
    status, body = _request(
        base, "POST", "/api/sites/clear-all", {"confirm": "remove-all"}
    )
    assert status == 200
    assert body["ok"] is True
    assert body["removed"] == 2
    assert websites.list_websites() == []


def test_settings_get_and_put(api_server):
    base, *_rest, settings = api_server
    status, body = _request(base, "GET", "/api/settings")
    assert status == 200
    keys = {f["key"] for f in body["fields"]}
    assert "timeout_seconds" in keys
    assert "notify_on" in keys
    assert any(f["type"] == "password" for f in body["fields"])

    status, body = _request(
        base, "PUT", "/api/settings", {"timeout_seconds": "15", "notify_on": "never"}
    )
    assert status == 200
    assert settings.get("timeout_seconds") == "15"
    assert settings.get("notify_on") == "never"


def test_import_csv(api_server):
    base, _, websites, *_ = api_server
    csv = b"Website name,URL\nDemo,https://demo.example\n"
    status, body = _request(
        base,
        "POST",
        "/api/import",
        {
            "filename": "sites.csv",
            "content_base64": base64.b64encode(csv).decode("ascii"),
        },
    )
    assert status == 200
    assert body["added_count"] >= 1
    assert any(s.domain == "demo.example" for s in websites.list_websites())

    status, body = _request(base, "POST", "/api/import", {"filename": "x.csv"})
    assert status == 400


def test_scan_job_lifecycle(api_server):
    base, _, websites, scans, _ = api_server
    site = websites.add_website("https://example.com")

    with patch.multiple(
        "whm.application.services",
        check_website=lambda *a, **k: healthy_check(),
        check_ssl=lambda *a, **k: healthy_check(),
        check_domain=lambda *a, **k: healthy_check(),
        check_dns=lambda *a, **k: dns_with_records(),
        detect_stack=lambda *a, **k: healthy_check(),
        dispatch_notifications=lambda *a, **k: [],
    ):
        status, body = _request(base, "POST", f"/api/sites/{site.id}/scan")
        assert status == 200
        job_id = body["job_id"]
        detail = None
        for _ in range(40):
            time.sleep(0.05)
            st, job = _request(base, "GET", f"/api/jobs/{job_id}")
            assert st == 200
            if job["status"] == "done":
                detail = job["detail"]
                break
            if job["status"] == "error":
                pytest.fail(job.get("error", "scan error"))
        assert detail is not None
        assert "summary" in detail


def test_scan_job_error(api_server):
    base, _, websites, *_ = api_server
    site = websites.add_website("https://example.com")

    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    with patch("whm.application.services.check_website", boom):
        status, body = _request(base, "POST", f"/api/sites/{site.id}/scan")
        job_id = body["job_id"]
        for _ in range(40):
            time.sleep(0.05)
            st, job = _request(base, "GET", f"/api/jobs/{job_id}")
            if job["status"] == "error":
                assert "simulated" in job["error"]
                return
        pytest.fail("job never errored")


def test_export_all_saves_portfolio(api_server, tmp_path, monkeypatch):
    base, _, websites, scans, _ = api_server
    status, body = _request(base, "POST", "/api/export-all", {"format": "excel"})
    assert status == 400

    site = websites.add_website("https://example.com", display_name="Example")
    result = HealthCheckResult(
        website_id=site.id,
        overall_status=HealthStatus.WARNING,
        risk_level=RiskLevel.MEDIUM,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.HEALTHY,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.WARNING,
        findings=[
            Finding("spf", "SPF", FindingStatus.MISSING, "none", "Add SPF"),
        ],
    )
    scans._health_checks.add(result)
    monkeypatch.setattr(
        "whm.presentation.webapi.save_portfolio_report_to_downloads",
        lambda rows, format="excel": tmp_path / "whm-all.xlsx",
    )
    (tmp_path / "whm-all.xlsx").write_bytes(b"PK")
    status, body = _request(base, "POST", "/api/export-all", {"format": "excel"})
    assert status == 200
    assert body["ok"] is True
    assert body["site_count"] == 1


def test_export_requires_check_then_saves(api_server, tmp_path, monkeypatch):
    base, _, websites, scans, _ = api_server
    site = websites.add_website("https://example.com")
    status, body = _request(base, "POST", f"/api/sites/{site.id}/export?format=csv")
    assert status == 400

    result = HealthCheckResult(
        website_id=site.id,
        overall_status=HealthStatus.HEALTHY,
        risk_level=RiskLevel.LOW,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.HEALTHY,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.HEALTHY,
        findings=[
            Finding("spf", "SPF", FindingStatus.CORRECT, "ok"),
        ],
    )
    scans._health_checks.add(result)
    monkeypatch.setattr(
        "whm.presentation.webapi.save_report_to_downloads",
        lambda site, latest, format="excel": tmp_path / f"report.{format}",
    )
    (tmp_path / "report.csv").write_text("ok", encoding="utf-8")
    status, body = _request(base, "POST", f"/api/sites/{site.id}/export?format=csv")
    assert status == 200
    assert body["ok"] is True
    assert body["format"] == "csv"
