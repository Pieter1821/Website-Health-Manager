"""Application services / use cases."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from whm.domain.models import (
    Customer,
    DnsSnapshot,
    HealthCheckResult,
    HealthStatus,
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
from whm.domain.hostnames import normalize_hostname, split_host_port
from whm.domain.status import site_facing_status, status_to_risk
from whm.infrastructure.dns_checker import check_dns, diff_dns_records
from whm.infrastructure.fingerprint import detect_stack
from whm.infrastructure.http_checker import check_website, normalize_url
from whm.infrastructure.importer import ImportResult, apply_import, parse_import_file
from whm.infrastructure.notifications import dispatch_notifications
from whm.infrastructure.ssl_checker import check_ssl
from whm.infrastructure.whois_checker import check_domain

logger = logging.getLogger(__name__)


def extract_domain(url: str) -> str:
    """Pull the hostname from a URL or bare domain string (normalized + punycode)."""
    normalized = normalize_url(url)
    host = urlparse(normalized).hostname
    if not host:
        raise ValueError(
            "That doesn’t look like a website. Try something like mybusiness.co.za"
        )
    return normalize_hostname(host)


ProgressCallback = Callable[[str], None]


class WebsiteService:
    """CRUD helpers for customers and websites."""

    def __init__(
        self,
        customers: CustomerRepository,
        websites: WebsiteRepository,
    ) -> None:
        self._customers = customers
        self._websites = websites

    def add_customer(self, name: str, notes: str = "") -> Customer:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Customer name is empty")
        for existing in self._customers.list_all():
            if existing.name.lower() == cleaned.lower():
                return existing
        return self._customers.add(Customer(name=cleaned, notes=notes))

    def list_customers(self) -> list[Customer]:
        return self._customers.list_all()

    def add_website(
        self,
        url: str,
        display_name: str = "",
        customer_id: Optional[int] = None,
        dkim_selectors: str = "s1,s2,em,default",
        check_interval: str = "manual",
    ) -> Website:
        clean_url = normalize_url(url)
        domain = extract_domain(clean_url)
        name = display_name.strip() or domain
        if customer_id is not None and self._customers.get(customer_id) is None:
            customer_id = None
        # Avoid duplicate rows for the same domain (common when pasting https:// again).
        for existing in self._websites.list_all():
            if existing.domain == domain:
                existing.url = clean_url
                if name and existing.display_name != name and display_name.strip():
                    existing.display_name = name
                if customer_id is not None:
                    existing.customer_id = customer_id
                return self._websites.update(existing)
        website = Website(
            url=clean_url,
            domain=domain,
            display_name=name,
            customer_id=customer_id,
            dkim_selectors=dkim_selectors,
            check_interval=check_interval or "manual",
        )
        return self._websites.add(website)

    def list_websites(self) -> list[Website]:
        return self._websites.list_all()

    def search(self, query: str) -> list[Website]:
        if not query.strip():
            return self.list_websites()
        return self._websites.search(query)

    def get_website(self, website_id: int) -> Optional[Website]:
        return self._websites.get(website_id)

    def update_website(self, website: Website) -> Website:
        return self._websites.update(website)

    def delete_website(self, website_id: int) -> None:
        self._websites.delete(website_id)

    def delete_all_websites(self) -> int:
        """Remove every website and its history. Returns how many were deleted."""
        sites = list(self._websites.list_all())
        for site in sites:
            if site.id is not None:
                self._websites.delete(site.id)
        return len(sites)

    def import_list(self, filename: str, data: bytes) -> ImportResult:
        """Import websites from an Excel (.xlsx) or CSV file."""
        rows = parse_import_file(filename, data)
        existing = {site.domain for site in self.list_websites()}
        return apply_import(
            rows,
            existing_domains=existing,
            add_customer=self.add_customer,
            add_website=self.add_website,
            extract_domain=extract_domain,
        )


class HealthScanService:
    """Run a full health scan and persist results."""

    def __init__(
        self,
        websites: WebsiteRepository,
        health_checks: HealthCheckRepository,
        dns_snapshots: DnsSnapshotRepository,
        settings: SettingsRepository,
    ) -> None:
        self._websites = websites
        self._health_checks = health_checks
        self._dns_snapshots = dns_snapshots
        self._settings = settings

    def _timeout(self) -> float:
        try:
            return float(self._settings.get("timeout_seconds", "10"))
        except ValueError:
            return 10.0

    def _dns_server(self) -> Optional[str]:
        value = self._settings.get("dns_server", "").strip().strip("()[]\"'")
        # Guard against pasted values like "8.8.8.8)" which break dnspython.
        if value and all(ch.isdigit() or ch == "." for ch in value):
            return value
        return value or None

    def scan_website(
        self,
        website_id: int,
        progress: Optional[ProgressCallback] = None,
        notify: bool = True,
    ) -> HealthCheckResult:
        website = self._websites.get(website_id)
        if website is None:
            raise ValueError(f"Website {website_id} not found")

        def report(message: str) -> None:
            logger.info("%s [%s]", message, website.domain)
            if progress:
                progress(message)

        timeout = self._timeout()
        dns_server = self._dns_server()
        started = time.perf_counter()
        result = HealthCheckResult(website_id=website_id)

        # Security headers, speed, and email-auth checks are skipped — they create
        # noise for website monitoring (operators often cannot change those).
        report("1/5 Checking if the website opens…")
        http = check_website(website.url, timeout=timeout)
        result.website_status = http["status"]
        result.response_time_ms = http.get("response_time_ms")
        result.findings.extend(http["findings"])
        result.raw["http"] = http.get("raw", {})

        report("2/5 Checking the security certificate…")
        ssl_host, ssl_port = split_host_port(website.url, default_port=443)
        ssl = check_ssl(ssl_host or website.domain, port=ssl_port, timeout=timeout)
        result.ssl_status = ssl["status"]
        result.findings.extend(ssl["findings"])
        result.raw["ssl"] = ssl.get("raw", {})

        report("3/5 Checking if the domain name is still registered…")
        # WHOIS always uses registrable domain (eTLD+1), never the subdomain alone.
        whois = check_domain(website.domain)
        result.domain_status = whois["status"]
        result.findings.extend(whois["findings"])
        result.raw["whois"] = whois.get("raw", {})

        report("4/5 Checking web address settings (DNS)…")
        dns = check_dns(
            website.domain,
            nameserver=dns_server,
            timeout=timeout,
            progress=report,
        )
        result.dns_status = dns["status"]
        result.findings.extend(dns["findings"])
        result.dns_records = dns.get("records", [])
        result.raw["dns"] = dns.get("raw", {})
        logger.info(
            "DNS settings summary for %s: status=%s records=%s",
            website.domain,
            result.dns_status.value,
            len(result.dns_records),
        )

        if dns.get("probe_ok", True):
            previous = self._dns_snapshots.latest_for_website(website_id)
            self._dns_snapshots.add(
                DnsSnapshot(website_id=website_id, records=list(result.dns_records))
            )
            if previous is not None:
                changes = diff_dns_records(previous.records, result.dns_records)
                result.raw["dns_changes"] = changes
                if changes:
                    from whm.domain.models import Finding, FindingStatus

                    summary = "; ".join(
                        f"{c['change']} {c['rtype']} {c['new_value'] or c['old_value']}"
                        for c in changes[:8]
                    )
                    logger.info("DNS settings changed for %s: %s", website.domain, summary)
                    result.findings.append(
                        Finding(
                            category="dns",
                            title="DNS settings changed",
                            status=FindingStatus.INFO,
                            message=summary,
                            details={"changes": changes},
                            recommendation="Confirm this change was intentional (for example after a migration).",
                        )
                    )
                else:
                    logger.info("DNS settings unchanged for %s", website.domain)
        else:
            result.raw["dns_changes"] = []
            result.raw["dns_snapshot_skipped"] = True
            logger.warning(
                "DNS snapshot skipped for %s (probe failed — not treating as settings change)",
                website.domain,
            )

        # Email auth (SPF/DKIM/DMARC/MX) is not part of website health scans.
        result.email_status = HealthStatus.HEALTHY
        result.raw["email"] = {"skipped": True}

        report("5/5 Detecting hosting and technology…")
        stack = detect_stack(website.url, timeout=timeout)
        result.findings.extend(stack["findings"])
        result.raw["stack"] = stack.get("raw", {})

        result.overall_status = site_facing_status(
            result.website_status,
            result.ssl_status,
            result.domain_status,
            result.dns_status,
        )
        result.risk_level = status_to_risk(result.overall_status)
        result.duration_ms = (time.perf_counter() - started) * 1000
        result.checked_at = utc_now()

        saved = self._health_checks.add(result)
        website.last_checked_at = saved.checked_at
        self._websites.update(website)

        if notify:
            try:
                sent = dispatch_notifications(
                    website, saved, dict(self._settings.get_all())
                )
                if sent:
                    logger.info("Notifications sent: %s", ", ".join(sent))
            except Exception:  # noqa: BLE001
                logger.exception("Notification dispatch failed")

        report("Done.")
        return saved

    def latest(self, website_id: int) -> Optional[HealthCheckResult]:
        return self._health_checks.latest_for_website(website_id)

    def history(self, website_id: int, limit: int = 20) -> list[HealthCheckResult]:
        return self._health_checks.history_for_website(website_id, limit=limit)

    def dns_diff(self, website_id: int) -> list[dict[str, str]]:
        latest = self._dns_snapshots.latest_for_website(website_id)
        previous = self._dns_snapshots.previous_for_website(website_id)
        if not latest or not previous:
            return []
        return diff_dns_records(previous.records, latest.records)


class SettingsService:
    def __init__(self, settings: SettingsRepository) -> None:
        self._settings = settings

    def get_all(self) -> dict[str, str]:
        return self._settings.get_all()

    def get(self, key: str, default: str = "") -> str:
        return self._settings.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._settings.set(key, value)
