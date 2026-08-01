"""Helpers to distinguish scanner-side network failures from real site issues."""

from __future__ import annotations

import re
from typing import Any

from whm.domain.models import Finding, FindingStatus

# Patterns that usually mean the scanner could not reach the target reliably.
_PROBE_PATTERNS = (
    r"getaddrinfo failed",
    r"name or service not known",
    r"temporary failure in name resolution",
    r"nodename nor servname provided",
    r"no address associated with hostname",
    r"failed to resolve",
    r"name resolution",
    r"dns operation timed out",
    r"the resolution lifetime expired",
    r"all connection attempts failed",
    r"connect call failed",
    r"timed out",
    r"timeout",
    r"network is unreachable",
    r"no route to host",
    r"network unreachable",
    r"connection aborted",
    r"connection reset",
    r"forcibly closed",
    r"unreachable",
    r"10054",  # WinError connection reset
    r"10051",  # network unreachable
    r"10053",  # connection aborted
    r"10060",  # connection timed out
    r"11001",  # WSAHOST_NOT_FOUND
    r"11002",  # WSATRY_AGAIN
    r"11004",  # WSANO_DATA
)


def is_probe_failure(message: str | BaseException | None) -> bool:
    """Return True when an error likely means the scan could not finish the check."""
    if message is None:
        return False
    text = str(message).lower()
    return any(re.search(pattern, text) for pattern in _PROBE_PATTERNS)


def probe_failed_finding(
    category: str,
    title: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> Finding:
    """Standard finding: check was inconclusive because the probe could not reach the target."""
    return Finding(
        category=category,
        title=title,
        status=FindingStatus.INCONCLUSIVE,
        message=message,
        recommendation=(
            "The check could not finish from here. "
            "Try again on a steadier connection before treating this as a site problem."
        ),
        details={**(details or {}), "probe_failed": True},
    )
