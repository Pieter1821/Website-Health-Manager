"""Ports (interfaces) that infrastructure implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from whm.domain.models import (
    Customer,
    DnsSnapshot,
    HealthCheckResult,
    Website,
)


class CustomerRepository(ABC):
    @abstractmethod
    def add(self, customer: Customer) -> Customer: ...

    @abstractmethod
    def list_all(self) -> list[Customer]: ...

    @abstractmethod
    def get(self, customer_id: int) -> Optional[Customer]: ...


class WebsiteRepository(ABC):
    @abstractmethod
    def add(self, website: Website) -> Website: ...

    @abstractmethod
    def list_all(self) -> list[Website]: ...

    @abstractmethod
    def get(self, website_id: int) -> Optional[Website]: ...

    @abstractmethod
    def search(self, query: str) -> list[Website]: ...

    @abstractmethod
    def update(self, website: Website) -> Website: ...

    @abstractmethod
    def delete(self, website_id: int) -> None: ...


class HealthCheckRepository(ABC):
    @abstractmethod
    def add(self, result: HealthCheckResult) -> HealthCheckResult: ...

    @abstractmethod
    def latest_for_website(self, website_id: int) -> Optional[HealthCheckResult]: ...

    @abstractmethod
    def history_for_website(
        self, website_id: int, limit: int = 20
    ) -> list[HealthCheckResult]: ...


class DnsSnapshotRepository(ABC):
    @abstractmethod
    def add(self, snapshot: DnsSnapshot) -> DnsSnapshot: ...

    @abstractmethod
    def latest_for_website(self, website_id: int) -> Optional[DnsSnapshot]: ...

    @abstractmethod
    def previous_for_website(self, website_id: int) -> Optional[DnsSnapshot]: ...


class SettingsRepository(ABC):
    @abstractmethod
    def get(self, key: str, default: str = "") -> str: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def get_all(self) -> dict[str, str]: ...
