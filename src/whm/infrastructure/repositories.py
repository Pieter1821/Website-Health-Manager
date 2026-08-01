"""SQLite implementations of domain repository ports."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

from whm.domain.models import (
    Customer,
    DnsRecord,
    DnsSnapshot,
    Finding,
    FindingStatus,
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
    Website,
    utc_now,
)
from whm.domain.ports import (
    CustomerRepository,
    DnsSnapshotRepository,
    HealthCheckRepository,
    SettingsRepository,
    WebsiteRepository,
)
from whm.infrastructure.database import locked


def _dt_to_str(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _str_to_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {
        "category": finding.category,
        "title": finding.title,
        "status": finding.status.value,
        "message": finding.message,
        "recommendation": finding.recommendation,
        "details": finding.details,
    }


def _dict_to_finding(data: dict[str, Any]) -> Finding:
    return Finding(
        category=data["category"],
        title=data["title"],
        status=FindingStatus(data["status"]),
        message=data["message"],
        recommendation=data.get("recommendation", ""),
        details=data.get("details", {}),
    )


def _record_to_dict(record: DnsRecord) -> dict[str, Any]:
    return {
        "rtype": record.rtype,
        "name": record.name,
        "value": record.value,
        "ttl": record.ttl,
        "priority": record.priority,
    }


def _dict_to_record(data: dict[str, Any]) -> DnsRecord:
    return DnsRecord(
        rtype=data["rtype"],
        name=data["name"],
        value=data["value"],
        ttl=data.get("ttl"),
        priority=data.get("priority"),
    )


class SqliteCustomerRepository(CustomerRepository):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, customer: Customer) -> Customer:
        with locked(self._conn):
            cur = self._conn.execute(
                "INSERT INTO customers (name, notes, created_at) VALUES (?, ?, ?)",
                (customer.name, customer.notes, _dt_to_str(customer.created_at)),
            )
            self._conn.commit()
            customer.id = int(cur.lastrowid)
            return customer

    def list_all(self) -> list[Customer]:
        with locked(self._conn):
            rows = self._conn.execute(
                "SELECT * FROM customers ORDER BY name COLLATE NOCASE"
            ).fetchall()
            return [self._row_to_customer(r) for r in rows]

    def get(self, customer_id: int) -> Optional[Customer]:
        with locked(self._conn):
            row = self._conn.execute(
                "SELECT * FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            return self._row_to_customer(row) if row else None

    @staticmethod
    def _row_to_customer(row: sqlite3.Row) -> Customer:
        return Customer(
            id=row["id"],
            name=row["name"],
            notes=row["notes"],
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
        )


class SqliteWebsiteRepository(WebsiteRepository):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, website: Website) -> Website:
        with locked(self._conn):
            if website.customer_id is not None:
                exists = self._conn.execute(
                    "SELECT 1 FROM customers WHERE id = ?",
                    (website.customer_id,),
                ).fetchone()
                if exists is None:
                    website.customer_id = None
            cur = self._conn.execute(
                """
                INSERT INTO websites
                (url, domain, display_name, customer_id, dkim_selectors, check_interval,
                 created_at, last_checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    website.url,
                    website.domain,
                    website.display_name,
                    website.customer_id,
                    website.dkim_selectors,
                    website.check_interval,
                    _dt_to_str(website.created_at),
                    _dt_to_str(website.last_checked_at),
                ),
            )
            self._conn.commit()
            website.id = int(cur.lastrowid)
            return website

    def list_all(self) -> list[Website]:
        with locked(self._conn):
            rows = self._conn.execute(
                "SELECT * FROM websites ORDER BY display_name COLLATE NOCASE"
            ).fetchall()
            return [self._row_to_website(r) for r in rows]

    def get(self, website_id: int) -> Optional[Website]:
        with locked(self._conn):
            row = self._conn.execute(
                "SELECT * FROM websites WHERE id = ?", (website_id,)
            ).fetchone()
            return self._row_to_website(row) if row else None

    def search(self, query: str) -> list[Website]:
        like = f"%{query.strip()}%"
        with locked(self._conn):
            rows = self._conn.execute(
                """
                SELECT w.* FROM websites w
                LEFT JOIN customers c ON c.id = w.customer_id
                WHERE w.display_name LIKE ?
                   OR w.domain LIKE ?
                   OR w.url LIKE ?
                   OR IFNULL(c.name, '') LIKE ?
                ORDER BY w.display_name COLLATE NOCASE
                """,
                (like, like, like, like),
            ).fetchall()
            return [self._row_to_website(r) for r in rows]

    def update(self, website: Website) -> Website:
        with locked(self._conn):
            if website.customer_id is not None:
                exists = self._conn.execute(
                    "SELECT 1 FROM customers WHERE id = ?",
                    (website.customer_id,),
                ).fetchone()
                if exists is None:
                    website.customer_id = None
            self._conn.execute(
                """
                UPDATE websites
                SET url = ?, domain = ?, display_name = ?, customer_id = ?,
                    dkim_selectors = ?, check_interval = ?, last_checked_at = ?
                WHERE id = ?
                """,
                (
                    website.url,
                    website.domain,
                    website.display_name,
                    website.customer_id,
                    website.dkim_selectors,
                    website.check_interval,
                    _dt_to_str(website.last_checked_at),
                    website.id,
                ),
            )
            self._conn.commit()
            return website

    def delete(self, website_id: int) -> None:
        with locked(self._conn):
            self._conn.execute(
                "DELETE FROM health_checks WHERE website_id = ?", (website_id,)
            )
            self._conn.execute(
                "DELETE FROM dns_snapshots WHERE website_id = ?", (website_id,)
            )
            self._conn.execute("DELETE FROM websites WHERE id = ?", (website_id,))
            self._conn.commit()

    @staticmethod
    def _row_to_website(row: sqlite3.Row) -> Website:
        keys = row.keys()
        return Website(
            id=row["id"],
            url=row["url"],
            domain=row["domain"],
            display_name=row["display_name"],
            customer_id=row["customer_id"],
            dkim_selectors=row["dkim_selectors"],
            check_interval=row["check_interval"] if "check_interval" in keys else "manual",
            created_at=_str_to_dt(row["created_at"]) or utc_now(),
            last_checked_at=_str_to_dt(row["last_checked_at"]),
        )


class SqliteHealthCheckRepository(HealthCheckRepository):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, result: HealthCheckResult) -> HealthCheckResult:
        with locked(self._conn):
            exists = self._conn.execute(
                "SELECT 1 FROM websites WHERE id = ?",
                (result.website_id,),
            ).fetchone()
            if exists is None:
                raise ValueError(
                    "That website was removed before the check could be saved. "
                    "Add it again and press Check."
                )
            cur = self._conn.execute(
                """
                INSERT INTO health_checks (
                    website_id, checked_at, overall_status, risk_level,
                    website_status, ssl_status, domain_status, dns_status, email_status,
                    response_time_ms, duration_ms, error_message,
                    findings_json, dns_records_json, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.website_id,
                    _dt_to_str(result.checked_at),
                    result.overall_status.value,
                    result.risk_level.value,
                    result.website_status.value,
                    result.ssl_status.value,
                    result.domain_status.value,
                    result.dns_status.value,
                    result.email_status.value,
                    result.response_time_ms,
                    result.duration_ms,
                    result.error_message,
                    json.dumps([_finding_to_dict(f) for f in result.findings]),
                    json.dumps([_record_to_dict(r) for r in result.dns_records]),
                    json.dumps(result.raw),
                ),
            )
            self._conn.commit()
            result.id = int(cur.lastrowid)
            return result

    def latest_for_website(self, website_id: int) -> Optional[HealthCheckResult]:
        with locked(self._conn):
            row = self._conn.execute(
                """
                SELECT * FROM health_checks
                WHERE website_id = ?
                ORDER BY checked_at DESC, id DESC
                LIMIT 1
                """,
                (website_id,),
            ).fetchone()
            return self._row_to_result(row) if row else None

    def history_for_website(
        self, website_id: int, limit: int = 20
    ) -> list[HealthCheckResult]:
        with locked(self._conn):
            rows = self._conn.execute(
                """
                SELECT * FROM health_checks
                WHERE website_id = ?
                ORDER BY checked_at DESC, id DESC
                LIMIT ?
                """,
                (website_id, limit),
            ).fetchall()
            return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> HealthCheckResult:
        findings = [_dict_to_finding(f) for f in json.loads(row["findings_json"])]
        records = [_dict_to_record(r) for r in json.loads(row["dns_records_json"])]
        return HealthCheckResult(
            id=row["id"],
            website_id=row["website_id"],
            checked_at=_str_to_dt(row["checked_at"]) or utc_now(),
            overall_status=HealthStatus(row["overall_status"]),
            risk_level=RiskLevel(row["risk_level"]),
            website_status=HealthStatus(row["website_status"]),
            ssl_status=HealthStatus(row["ssl_status"]),
            domain_status=HealthStatus(row["domain_status"]),
            dns_status=HealthStatus(row["dns_status"]),
            email_status=HealthStatus(row["email_status"]),
            response_time_ms=row["response_time_ms"],
            duration_ms=row["duration_ms"],
            error_message=row["error_message"] or "",
            findings=findings,
            dns_records=records,
            raw=json.loads(row["raw_json"] or "{}"),
        )


class SqliteDnsSnapshotRepository(DnsSnapshotRepository):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, snapshot: DnsSnapshot) -> DnsSnapshot:
        with locked(self._conn):
            exists = self._conn.execute(
                "SELECT 1 FROM websites WHERE id = ?",
                (snapshot.website_id,),
            ).fetchone()
            if exists is None:
                return snapshot
            cur = self._conn.execute(
                """
                INSERT INTO dns_snapshots (website_id, captured_at, records_json)
                VALUES (?, ?, ?)
                """,
                (
                    snapshot.website_id,
                    _dt_to_str(snapshot.captured_at),
                    json.dumps([_record_to_dict(r) for r in snapshot.records]),
                ),
            )
            self._conn.commit()
            snapshot.id = int(cur.lastrowid)
            return snapshot

    def latest_for_website(self, website_id: int) -> Optional[DnsSnapshot]:
        with locked(self._conn):
            row = self._conn.execute(
                """
                SELECT * FROM dns_snapshots
                WHERE website_id = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """,
                (website_id,),
            ).fetchone()
            return self._row_to_snapshot(row) if row else None

    def previous_for_website(self, website_id: int) -> Optional[DnsSnapshot]:
        with locked(self._conn):
            row = self._conn.execute(
                """
                SELECT * FROM dns_snapshots
                WHERE website_id = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT 1 OFFSET 1
                """,
                (website_id,),
            ).fetchone()
            return self._row_to_snapshot(row) if row else None

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> DnsSnapshot:
        records = [_dict_to_record(r) for r in json.loads(row["records_json"])]
        return DnsSnapshot(
            id=row["id"],
            website_id=row["website_id"],
            captured_at=_str_to_dt(row["captured_at"]) or utc_now(),
            records=records,
        )


class SqliteSettingsRepository(SettingsRepository):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str, default: str = "") -> str:
        with locked(self._conn):
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with locked(self._conn):
            self._conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            self._conn.commit()

    def get_all(self) -> dict[str, str]:
        with locked(self._conn):
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}
