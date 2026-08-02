"""Application entrypoint."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from whm.application.scheduler import SchedulerService
from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.infrastructure.cloud_client import CloudApiClient
from whm.infrastructure.cloud_config import load_cloud_config
from whm.infrastructure.cloud_repositories import (
    CloudCustomerRepository,
    CloudDnsSnapshotRepository,
    CloudHealthCheckRepository,
    CloudSettingsRepository,
    CloudWebsiteRepository,
)
from whm.infrastructure.database import connect, default_db_path, initialize_database
from whm.infrastructure.repositories import (
    SqliteCustomerRepository,
    SqliteDnsSnapshotRepository,
    SqliteHealthCheckRepository,
    SqliteSettingsRepository,
    SqliteWebsiteRepository,
)


def setup_logging() -> None:
    """Write logs under ~/.whm/logs while also echoing to stderr."""
    log_dir = Path.home() / ".whm" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "whm.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    logging.getLogger("whois").setLevel(logging.CRITICAL)
    logging.getLogger("whois.whois").setLevel(logging.CRITICAL)


def build_services(db_path: Path | None = None):
    """
    Wire repositories + services.

    If ~/.whm/cloud.json (or WHM_API_URL + WHM_API_TOKEN) is set, use Cloudflare D1
    via the Worker API. Otherwise use local SQLite under ~/.whm/whm.db.
    """
    cloud = load_cloud_config()
    force_local = (os.environ.get("WHM_STORAGE") or "").strip().lower() in {
        "local",
        "sqlite",
    }
    if cloud and cloud.enabled and not force_local:
        logging.getLogger(__name__).info(
            "Using Cloudflare D1 via %s", cloud.api_url
        )
        client = CloudApiClient(cloud)
        customers = CloudCustomerRepository(client)
        websites = CloudWebsiteRepository(client)
        health = CloudHealthCheckRepository(client)
        dns = CloudDnsSnapshotRepository(client)
        settings = CloudSettingsRepository(client)
        website_service = WebsiteService(customers, websites)
        scan_service = HealthScanService(websites, health, dns, settings)
        settings_service = SettingsService(settings)
        return website_service, scan_service, settings_service, None

    conn = connect(db_path or default_db_path())
    initialize_database(conn)
    customers = SqliteCustomerRepository(conn)
    websites = SqliteWebsiteRepository(conn)
    health = SqliteHealthCheckRepository(conn)
    dns = SqliteDnsSnapshotRepository(conn)
    settings = SqliteSettingsRepository(conn)
    website_service = WebsiteService(customers, websites)
    scan_service = HealthScanService(websites, health, dns, settings)
    settings_service = SettingsService(settings)
    return website_service, scan_service, settings_service, conn


def main() -> None:
    setup_logging()
    logging.getLogger(__name__).info("Starting Website Health Manager")
    website_service, scan_service, settings_service, _conn = build_services()
    scheduler = SchedulerService(website_service, scan_service, settings_service)

    ui_mode = (os.environ.get("WHM_UI") or "web").strip().lower()
    if "--tk" in sys.argv:
        ui_mode = "tk"

    if ui_mode == "tk":
        from whm.presentation.launcher import launch_tk_fallback

        launch_tk_fallback(website_service, scan_service, settings_service, scheduler)
        return

    from whm.presentation.launcher import launch_web_desktop

    raise SystemExit(
        launch_web_desktop(website_service, scan_service, settings_service, scheduler)
    )


if __name__ == "__main__":
    main()
