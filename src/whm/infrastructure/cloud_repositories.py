"""Repository adapters that persist via the Cloudflare Worker / D1 API."""

from __future__ import annotations

import json
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
from whm.infrastructure.cloud_client import CloudApiClient, CloudApiError


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


def _row_to_customer(row: dict[str, Any]) -> Customer:
    return Customer(
        id=int(row["id"]),
        name=row["name"],
        notes=row.get("notes") or "",
        created_at=_str_to_dt(row.get("created_at")) or utc_now(),
    )


def _row_to_website(row: dict[str, Any]) -> Website:
    return Website(
        id=int(row["id"]),
        url=row["url"],
        domain=row["domain"],
        display_name=row["display_name"],
        customer_id=row.get("customer_id"),
        dkim_selectors=row.get("dkim_selectors") or "s1,s2,em,default",
        check_interval=row.get("check_interval") or "manual",
        created_at=_str_to_dt(row.get("created_at")) or utc_now(),
        last_checked_at=_str_to_dt(row.get("last_checked_at")),
    )


def _row_to_result(row: dict[str, Any]) -> HealthCheckResult:
    findings = [_dict_to_finding(f) for f in json.loads(row.get("findings_json") or "[]")]
    records = [_dict_to_record(r) for r in json.loads(row.get("dns_records_json") or "[]")]
    return HealthCheckResult(
        id=int(row["id"]),
        website_id=int(row["website_id"]),
        checked_at=_str_to_dt(row.get("checked_at")) or utc_now(),
        overall_status=HealthStatus(row["overall_status"]),
        risk_level=RiskLevel(row["risk_level"]),
        website_status=HealthStatus(row["website_status"]),
        ssl_status=HealthStatus(row["ssl_status"]),
        domain_status=HealthStatus(row["domain_status"]),
        dns_status=HealthStatus(row["dns_status"]),
        email_status=HealthStatus(row.get("email_status") or "healthy"),
        response_time_ms=row.get("response_time_ms"),
        duration_ms=row.get("duration_ms"),
        error_message=row.get("error_message") or "",
        findings=findings,
        dns_records=records,
        raw=json.loads(row.get("raw_json") or "{}"),
    )


def _row_to_snapshot(row: dict[str, Any]) -> DnsSnapshot:
    records = [_dict_to_record(r) for r in json.loads(row.get("records_json") or "[]")]
    return DnsSnapshot(
        id=int(row["id"]),
        website_id=int(row["website_id"]),
        captured_at=_str_to_dt(row.get("captured_at")) or utc_now(),
        records=records,
    )


class CloudCustomerRepository(CustomerRepository):
    def __init__(self, client: CloudApiClient) -> None:
        self._api = client

    def add(self, customer: Customer) -> Customer:
        row = self._api.post(
            "/api/customers",
            {
                "name": customer.name,
                "notes": customer.notes,
                "created_at": _dt_to_str(customer.created_at),
            },
        )
        return _row_to_customer(row)

    def list_all(self) -> list[Customer]:
        data = self._api.get("/api/customers")
        return [_row_to_customer(r) for r in data.get("customers") or []]

    def get(self, customer_id: int) -> Optional[Customer]:
        try:
            row = self._api.get(f"/api/customers/{customer_id}")
        except CloudApiError as exc:
            if exc.status_code == 404:
                return None
            raise
        return _row_to_customer(row)

    def delete(self, customer_id: int) -> None:
        self._api.delete(f"/api/customers/{customer_id}")


class CloudWebsiteRepository(WebsiteRepository):
    def __init__(self, client: CloudApiClient) -> None:
        self._api = client

    def add(self, website: Website) -> Website:
        row = self._api.post(
            "/api/websites",
            {
                "url": website.url,
                "domain": website.domain,
                "display_name": website.display_name,
                "customer_id": website.customer_id,
                "dkim_selectors": website.dkim_selectors,
                "check_interval": website.check_interval,
                "created_at": _dt_to_str(website.created_at),
                "last_checked_at": _dt_to_str(website.last_checked_at),
            },
        )
        return _row_to_website(row)

    def list_all(self) -> list[Website]:
        data = self._api.get("/api/websites")
        return [_row_to_website(r) for r in data.get("websites") or []]

    def get(self, website_id: int) -> Optional[Website]:
        try:
            row = self._api.get(f"/api/websites/{website_id}")
        except CloudApiError as exc:
            if exc.status_code == 404:
                return None
            raise
        return _row_to_website(row)

    def search(self, query: str) -> list[Website]:
        data = self._api.get("/api/websites", q=query)
        return [_row_to_website(r) for r in data.get("websites") or []]

    def update(self, website: Website) -> Website:
        row = self._api.put(
            f"/api/websites/{website.id}",
            {
                "url": website.url,
                "domain": website.domain,
                "display_name": website.display_name,
                "customer_id": website.customer_id,
                "dkim_selectors": website.dkim_selectors,
                "check_interval": website.check_interval,
                "last_checked_at": _dt_to_str(website.last_checked_at),
            },
        )
        return _row_to_website(row)

    def delete(self, website_id: int) -> None:
        self._api.delete(f"/api/websites/{website_id}")


class CloudHealthCheckRepository(HealthCheckRepository):
    def __init__(self, client: CloudApiClient) -> None:
        self._api = client

    def add(self, result: HealthCheckResult) -> HealthCheckResult:
        row = self._api.post(
            f"/api/websites/{result.website_id}/health-checks",
            {
                "checked_at": _dt_to_str(result.checked_at),
                "overall_status": result.overall_status.value,
                "risk_level": result.risk_level.value,
                "website_status": result.website_status.value,
                "ssl_status": result.ssl_status.value,
                "domain_status": result.domain_status.value,
                "dns_status": result.dns_status.value,
                "email_status": result.email_status.value,
                "response_time_ms": result.response_time_ms,
                "duration_ms": result.duration_ms,
                "error_message": result.error_message,
                "findings": [_finding_to_dict(f) for f in result.findings],
                "dns_records": [_record_to_dict(r) for r in result.dns_records],
                "raw": result.raw,
            },
        )
        return _row_to_result(row)

    def latest_for_website(self, website_id: int) -> Optional[HealthCheckResult]:
        data = self._api.get(f"/api/websites/{website_id}/health-checks/latest")
        row = data.get("check")
        return _row_to_result(row) if row else None

    def history_for_website(
        self, website_id: int, limit: int = 20
    ) -> list[HealthCheckResult]:
        data = self._api.get(
            f"/api/websites/{website_id}/health-checks", limit=limit
        )
        return [_row_to_result(r) for r in data.get("checks") or []]


class CloudDnsSnapshotRepository(DnsSnapshotRepository):
    def __init__(self, client: CloudApiClient) -> None:
        self._api = client

    def add(self, snapshot: DnsSnapshot) -> DnsSnapshot:
        row = self._api.post(
            f"/api/websites/{snapshot.website_id}/dns-snapshots",
            {
                "captured_at": _dt_to_str(snapshot.captured_at),
                "records": [_record_to_dict(r) for r in snapshot.records],
            },
        )
        if row.get("skipped"):
            return snapshot
        return _row_to_snapshot(row)

    def latest_for_website(self, website_id: int) -> Optional[DnsSnapshot]:
        data = self._api.get(f"/api/websites/{website_id}/dns-snapshots/latest")
        row = data.get("snapshot")
        return _row_to_snapshot(row) if row else None

    def previous_for_website(self, website_id: int) -> Optional[DnsSnapshot]:
        data = self._api.get(f"/api/websites/{website_id}/dns-snapshots/previous")
        row = data.get("snapshot")
        return _row_to_snapshot(row) if row else None


class CloudSettingsRepository(SettingsRepository):
    def __init__(self, client: CloudApiClient) -> None:
        self._api = client
        self._cache: Optional[dict[str, str]] = None

    def _load(self) -> dict[str, str]:
        if self._cache is None:
            data = self._api.get("/api/settings")
            self._cache = dict(data.get("settings") or {})
        return self._cache

    def get(self, key: str, default: str = "") -> str:
        return self._load().get(key, default)

    def set(self, key: str, value: str) -> None:
        settings = dict(self._load())
        settings[key] = value
        self._api.put("/api/settings", {"settings": {key: value}})
        self._cache = settings

    def get_all(self) -> dict[str, str]:
        return dict(self._load())
