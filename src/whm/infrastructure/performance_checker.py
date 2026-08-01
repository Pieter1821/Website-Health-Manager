"""Simple performance timings (Phase 3)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.infrastructure.http_checker import normalize_url


def check_performance(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Measure connect-ish timing and full download time with httpx."""
    target = normalize_url(url)
    started = time.perf_counter()
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=True) as client:
            t0 = time.perf_counter()
            response = client.get(target)
            first_byte_ms = (time.perf_counter() - t0) * 1000
            body = response.content
            total_ms = (time.perf_counter() - started) * 1000
            size = len(body)
    except Exception as exc:  # noqa: BLE001
        if is_probe_failure(exc):
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": [
                    probe_failed_finding("performance", "Speed check inconclusive", str(exc))
                ],
                "raw": {"probe_failed": True},
            }
        return {
            "status": HealthStatus.WARNING,
            "findings": [
                Finding(
                    category="performance",
                    title="Speed check failed",
                    status=FindingStatus.INCORRECT,
                    message=str(exc),
                )
            ],
            "raw": {"error": str(exc)},
        }

    findings = [
        Finding(
            category="performance",
            title="Time to first response",
            status=FindingStatus.CORRECT if first_byte_ms < 2000 else FindingStatus.INCORRECT,
            message=f"{first_byte_ms:.0f} milliseconds",
            recommendation=(
                "Under 2 seconds is usually fine. Slow responses may mean hosting or network issues."
                if first_byte_ms >= 2000
                else ""
            ),
            details={"first_byte_ms": first_byte_ms},
        ),
        Finding(
            category="performance",
            title="Full page download",
            status=FindingStatus.CORRECT if total_ms < 5000 else FindingStatus.INCORRECT,
            message=f"{total_ms:.0f} milliseconds ({size / 1024:.1f} KB)",
            details={"total_ms": total_ms, "bytes": size},
        ),
    ]
    status = HealthStatus.HEALTHY
    if first_byte_ms >= 5000 or total_ms >= 8000:
        status = HealthStatus.WARNING
    return {
        "status": status,
        "findings": findings,
        "raw": {
            "first_byte_ms": first_byte_ms,
            "total_ms": total_ms,
            "bytes": size,
            "status_code": response.status_code,
        },
    }
