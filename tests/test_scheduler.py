"""Scheduler interval and tick behaviour (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from whm.application.scheduler import INTERVAL_SECONDS, SchedulerService
from whm.domain.models import Website


def _scheduler(sites, settings_interval="manual"):
    websites = MagicMock()
    websites.list_websites.return_value = sites
    scans = MagicMock()
    settings = MagicMock()
    settings.get.side_effect = lambda key, default="": (
        settings_interval if key == "check_interval" else default
    )
    return SchedulerService(websites, scans, settings), scans


def test_effective_interval_site_wins():
    site = Website(
        url="https://a.com",
        domain="a.com",
        display_name="A",
        id=1,
        check_interval="hourly",
    )
    sched, _ = _scheduler([site], settings_interval="daily")
    assert sched._effective_interval(site) == "hourly"


def test_effective_interval_falls_back_to_settings():
    site = Website(
        url="https://a.com",
        domain="a.com",
        display_name="A",
        id=1,
        check_interval="manual",
    )
    sched, _ = _scheduler([site], settings_interval="daily")
    assert sched._effective_interval(site) == "daily"
    assert INTERVAL_SECONDS["daily"] == 24 * 3600


def test_tick_skips_manual(monkeypatch):
    site = Website(
        url="https://a.com",
        domain="a.com",
        display_name="A",
        id=1,
        check_interval="manual",
    )
    sched, scans = _scheduler([site], settings_interval="manual")
    monkeypatch.setattr("whm.application.scheduler.time.time", lambda: 1_700_000_000)
    sched._tick()
    scans.scan_website.assert_not_called()


def test_tick_scans_when_due(monkeypatch):
    site = Website(
        url="https://a.com",
        domain="a.com",
        display_name="A",
        id=1,
        check_interval="hourly",
        last_checked_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    sched, scans = _scheduler([site])
    now = 1_700_000_000.0
    monkeypatch.setattr("whm.application.scheduler.time.time", lambda: now)
    sched._tick()
    scans.scan_website.assert_called_once_with(1, notify=True)
    assert sched._last_run[1] == now


def test_tick_honours_recent_last_checked(monkeypatch):
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    site = Website(
        url="https://a.com",
        domain="a.com",
        display_name="A",
        id=1,
        check_interval="hourly",
        last_checked_at=recent,
    )
    sched, scans = _scheduler([site])
    monkeypatch.setattr(
        "whm.application.scheduler.time.time",
        lambda: recent.timestamp() + 60,
    )
    sched._tick()
    scans.scan_website.assert_not_called()


def test_tick_records_last_run_on_failure(monkeypatch):
    site = Website(
        url="https://a.com",
        domain="a.com",
        display_name="A",
        id=1,
        check_interval="hourly",
        last_checked_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    sched, scans = _scheduler([site])
    scans.scan_website.side_effect = RuntimeError("boom")
    now = 1_700_000_000.0
    monkeypatch.setattr("whm.application.scheduler.time.time", lambda: now)
    sched._tick()
    assert sched._last_run[1] == now


def test_start_stop_idempotent():
    sched, _ = _scheduler([])
    sched.start()
    first = sched._thread
    sched.start()
    assert sched._thread is first
    sched.stop()
    assert sched._stop.is_set()
