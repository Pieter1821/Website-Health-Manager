"""Shared fixtures for offline WHM tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.domain.models import DnsRecord, Finding, FindingStatus, HealthStatus
from whm.infrastructure.database import connect, initialize_database
from whm.infrastructure.repositories import (
    SqliteCustomerRepository,
    SqliteDnsSnapshotRepository,
    SqliteHealthCheckRepository,
    SqliteSettingsRepository,
    SqliteWebsiteRepository,
)


@pytest.fixture
def db_conn(tmp_path: Path):
    conn = connect(tmp_path / "whm-test.db")
    initialize_database(conn)
    yield conn
    conn.close()


@pytest.fixture
def repos(db_conn):
    return {
        "customers": SqliteCustomerRepository(db_conn),
        "websites": SqliteWebsiteRepository(db_conn),
        "health": SqliteHealthCheckRepository(db_conn),
        "dns": SqliteDnsSnapshotRepository(db_conn),
        "settings": SqliteSettingsRepository(db_conn),
    }


@pytest.fixture
def website_service(repos):
    return WebsiteService(repos["customers"], repos["websites"])


@pytest.fixture
def scan_service(repos):
    return HealthScanService(
        repos["websites"],
        repos["health"],
        repos["dns"],
        repos["settings"],
    )


@pytest.fixture
def settings_service(repos):
    return SettingsService(repos["settings"])


def healthy_check(**extra):
    """Minimal checker return shape used by scan orchestration stubs."""
    payload = {
        "status": HealthStatus.HEALTHY,
        "findings": [],
        "response_time_ms": 42.0,
        "records": [],
        "probe_ok": True,
        "raw": {},
    }
    payload.update(extra)
    return payload


def dns_with_records(domain: str = "example.com"):
    return healthy_check(
        records=[
            DnsRecord("A", domain, "203.0.113.10"),
            DnsRecord("NS", domain, "ns1.example.net"),
        ],
        raw={"domain": domain},
    )


def warn_finding(category: str = "ssl", title: str = "Soon"):
    return Finding(category, title, FindingStatus.INCORRECT, "needs work", "Fix it")
