"""Launch the beautiful web UI in a desktop app window."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional

from whm.application.scheduler import SchedulerService
from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.presentation.webapi import start_server

logger = logging.getLogger(__name__)


def _wait_for_server(url: str, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.15)
    return False


def _find_browser() -> Optional[str]:
    # Prefer Chrome; Edge is only a fallback.
    candidates = [
        os.environ.get("WHM_BROWSER", ""),
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        shutil.which("msedge"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _keep_alive(message: str) -> None:
    """Keep the local server running until the user stops the terminal."""
    print(message)
    print("Press Ctrl+C in this terminal to quit Website Health Manager.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping…")


def launch_web_desktop(
    websites: WebsiteService,
    scans: HealthScanService,
    settings: SettingsService,
    scheduler: Optional[SchedulerService] = None,
    cloud_client=None,
) -> int:
    """
    Start local API + open Edge/Chrome in app mode (frameless desktop feel).
    Returns process exit code-ish (0 on clean close).
    """
    server, url = start_server(
        websites, scans, settings, cloud_client=cloud_client
    )
    if scheduler:
        scheduler.start()

    if not _wait_for_server(url):
        logger.error("UI server failed to start")
        server.shutdown()
        return 1

    browser = _find_browser()
    proc: subprocess.Popen[bytes] | None = None
    try:
        if browser is None:
            logger.warning("No Edge/Chrome found; opening default browser")
            import webbrowser

            webbrowser.open(url)
            _keep_alive(f"Website Health Manager is running at {url}")
        else:
            user_data = os.path.join(os.path.expanduser("~"), ".whm", "browser-profile")
            os.makedirs(user_data, exist_ok=True)
            args = [
                browser,
                f"--app={url}",
                f"--user-data-dir={user_data}",
                "--new-window",
                "--disable-extensions",
                "--disable-plugins",
                "--no-first-run",
                "--no-default-browser-check",
                # Leave room above the Windows taskbar so the full table is usable.
                "--window-size=1400,820",
                "--window-position=60,40",
            ]
            logger.info("Opening desktop UI with %s", browser)
            proc = subprocess.Popen(args)
            # Edge/Chrome often exit the launcher process immediately while the
            # app window stays open. Never shut the API down just because of that.
            _keep_alive(f"Website Health Manager is running at {url}")
    finally:
        if scheduler:
            scheduler.stop()
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
    return 0


def launch_tk_fallback(
    websites: WebsiteService,
    scans: HealthScanService,
    settings: SettingsService,
    scheduler: Optional[SchedulerService] = None,
) -> None:
    import tkinter as tk

    from whm.presentation.app import WebsiteHealthApp

    root = tk.Tk()
    app_holder: dict[str, WebsiteHealthApp] = {}

    def on_scheduled(website_id: int) -> None:
        app = app_holder.get("app")
        if app is None:
            return
        root.after(0, app.refresh_list)

    if scheduler is not None:
        scheduler._on_scan_complete = on_scheduled  # noqa: SLF001
        scheduler.start()

    app = WebsiteHealthApp(root, websites, scans, settings, scheduler=scheduler)
    app_holder["app"] = app

    def on_close() -> None:
        if scheduler:
            scheduler.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
