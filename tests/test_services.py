"""WebsiteService + HealthScanService orchestration (offline)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from whm.domain.models import DnsRecord, HealthStatus
from tests.conftest import dns_with_records, healthy_check


def test_add_customer_empty_raises(website_service):
    with pytest.raises(ValueError, match="empty"):
        website_service.add_customer("   ")


def test_add_customer_reuses_case_insensitive(website_service):
    a = website_service.add_customer("Acme Corp")
    b = website_service.add_customer("acme corp")
    assert a.id == b.id


def test_add_website_normalizes_and_dedupes(website_service):
    first = website_service.add_website("example.com", display_name="Example")
    second = website_service.add_website(
        "https://example.com/path", display_name="Example Site"
    )
    assert first.id == second.id
    assert second.url.startswith("https://")
    assert second.display_name == "Example Site"
    assert len(website_service.list_websites()) == 1


def test_add_website_bad_customer_id_ignored(website_service):
    site = website_service.add_website("https://example.com", customer_id=99999)
    assert site.customer_id is None


def test_delete_website_removes_health_and_dns(website_service, scan_service, repos):
    site = website_service.add_website("https://example.com")
    with patch.multiple(
        "whm.application.services",
        check_website=lambda *a, **k: healthy_check(),
        check_ssl=lambda *a, **k: healthy_check(),
        check_domain=lambda *a, **k: healthy_check(),
        check_dns=lambda *a, **k: dns_with_records(),
        detect_stack=lambda *a, **k: healthy_check(),
        dispatch_notifications=lambda *a, **k: [],
    ):
        scan_service.scan_website(site.id, notify=False)

    assert repos["health"].latest_for_website(site.id) is not None
    assert repos["dns"].latest_for_website(site.id) is not None

    website_service.delete_website(site.id)
    assert website_service.get_website(site.id) is None
    assert repos["health"].latest_for_website(site.id) is None
    assert repos["dns"].latest_for_website(site.id) is None


def test_scan_missing_website_raises(scan_service):
    with pytest.raises(ValueError, match="not found"):
        scan_service.scan_website(404)


def test_scan_website_persists_and_reports_progress(website_service, scan_service):
    site = website_service.add_website("https://example.com")
    messages: list[str] = []

    with patch.multiple(
        "whm.application.services",
        check_website=lambda *a, **k: healthy_check(response_time_ms=88),
        check_ssl=lambda *a, **k: healthy_check(),
        check_domain=lambda *a, **k: healthy_check(),
        check_dns=lambda *a, **k: dns_with_records(),
        detect_stack=lambda *a, **k: healthy_check(),
        dispatch_notifications=lambda *a, **k: ["desktop"],
    ):
        result = scan_service.scan_website(
            site.id, progress=messages.append, notify=True
        )

    assert result.overall_status == HealthStatus.HEALTHY
    assert result.response_time_ms == 88
    assert messages[-1] == "Done."
    assert any("website opens" in m.lower() for m in messages)
    refreshed = website_service.get_website(site.id)
    assert refreshed is not None
    assert refreshed.last_checked_at is not None
    assert scan_service.latest(site.id) is not None


def test_scan_skips_notifications_when_disabled(website_service, scan_service):
    site = website_service.add_website("https://example.com")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return []

    with patch.multiple(
        "whm.application.services",
        check_website=lambda *a, **k: healthy_check(),
        check_ssl=lambda *a, **k: healthy_check(),
        check_domain=lambda *a, **k: healthy_check(),
        check_dns=lambda *a, **k: dns_with_records(),
        detect_stack=lambda *a, **k: healthy_check(),
        dispatch_notifications=boom,
    ):
        scan_service.scan_website(site.id, notify=False)
    assert called["n"] == 0


def test_scan_skips_dns_snapshot_on_probe_fail(website_service, scan_service, repos):
    site = website_service.add_website("https://example.com")
    with patch.multiple(
        "whm.application.services",
        check_website=lambda *a, **k: healthy_check(),
        check_ssl=lambda *a, **k: healthy_check(),
        check_domain=lambda *a, **k: healthy_check(),
        check_dns=lambda *a, **k: {
            "status": HealthStatus.UNKNOWN,
            "findings": [],
            "records": [],
            "probe_ok": False,
            "raw": {"probe_failed": True},
        },
        detect_stack=lambda *a, **k: healthy_check(),
        dispatch_notifications=lambda *a, **k: [],
    ):
        result = scan_service.scan_website(site.id, notify=False)

    assert result.raw.get("dns_snapshot_skipped") is True
    assert repos["dns"].latest_for_website(site.id) is None


def test_scan_detects_dns_changes(website_service, scan_service):
    site = website_service.add_website("https://example.com")
    first = [
        DnsRecord("A", "example.com", "203.0.113.10"),
        DnsRecord("NS", "example.com", "ns1.example.net"),
    ]
    second = [
        DnsRecord("A", "example.com", "203.0.113.99"),
        DnsRecord("NS", "example.com", "ns1.example.net"),
    ]
    calls = {"n": 0}

    def fake_dns(*a, **k):
        calls["n"] += 1
        records = first if calls["n"] == 1 else second
        return healthy_check(records=records)

    with patch.multiple(
        "whm.application.services",
        check_website=lambda *a, **k: healthy_check(),
        check_ssl=lambda *a, **k: healthy_check(),
        check_domain=lambda *a, **k: healthy_check(),
        check_dns=fake_dns,
        detect_stack=lambda *a, **k: healthy_check(),
        dispatch_notifications=lambda *a, **k: [],
    ):
        scan_service.scan_website(site.id, notify=False)
        result = scan_service.scan_website(site.id, notify=False)

    assert any(f.title == "DNS settings changed" for f in result.findings)
    assert scan_service.dns_diff(site.id)


def test_dns_server_strips_junk(scan_service, repos):
    repos["settings"].set("dns_server", "8.8.8.8)")
    assert scan_service._dns_server() == "8.8.8.8"
    repos["settings"].set("dns_server", "not-an-ip")
    # Non-IP text is still returned (custom resolvers may be hostnames).
    assert scan_service._dns_server() == "not-an-ip"
    repos["settings"].set("dns_server", "")
    assert scan_service._dns_server() is None


def test_dns_diff_needs_two_snapshots(website_service, scan_service, repos):
    from whm.domain.models import DnsSnapshot

    site = website_service.add_website("https://example.com")
    assert scan_service.dns_diff(site.id) == []
    repos["dns"].add(
        DnsSnapshot(
            website_id=site.id,
            records=[DnsRecord("A", "example.com", "1.2.3.4")],
            captured_at=datetime.now(timezone.utc),
        )
    )
    assert scan_service.dns_diff(site.id) == []
