"""Background schedule runner (Phase 2)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timezone
from typing import Callable, Optional

from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.domain.models import Website

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = {
    "manual": 0,
    "hourly": 3600,
    "every_6_hours": 6 * 3600,
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
}


ProgressCallback = Callable[[str], None]


class SchedulerService:
    """Polls websites that have an automatic check interval."""

    def __init__(
        self,
        websites: WebsiteService,
        scans: HealthScanService,
        settings: SettingsService,
        on_scan_complete: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._websites = websites
        self._scans = scans
        self._settings = settings
        self._on_scan_complete = on_scan_complete
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_run: dict[int, float] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="whm-scheduler", daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler tick failed")
            self._stop.wait(30)

    def _effective_interval(self, site: Website) -> str:
        site_interval = getattr(site, "check_interval", None) or "manual"
        if site_interval and site_interval != "manual":
            return site_interval
        return self._settings.get("check_interval", "manual") or "manual"

    def _tick(self) -> None:
        now = time.time()
        for site in self._websites.list_websites():
            if site.id is None:
                continue
            interval_key = self._effective_interval(site)
            seconds = INTERVAL_SECONDS.get(interval_key, 0)
            if seconds <= 0:
                continue
            last = self._last_run.get(site.id, 0)
            # Also honour last_checked_at from DB so restarts don't immediately re-scan.
            if site.last_checked_at:
                last = max(last, site.last_checked_at.replace(tzinfo=timezone.utc).timestamp())
            if now - last < seconds:
                continue
            logger.info("Scheduled scan for %s (%s)", site.domain, interval_key)
            try:
                self._scans.scan_website(site.id, notify=True)
                self._last_run[site.id] = time.time()
                if self._on_scan_complete:
                    self._on_scan_complete(site.id)
            except Exception:  # noqa: BLE001
                logger.exception("Scheduled scan failed for %s", site.domain)
                self._last_run[site.id] = time.time()
