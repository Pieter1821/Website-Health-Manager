"""Helpers to distinguish local probe/network failures from real site issues."""

from __future__ import annotations

import re
from typing import Any

from whm.domain.models import Finding, FindingStatus

# Patterns that usually mean *our* network/DNS failed — not the customer's server config.
_PROBE_PATTERNS = (
    r"getaddrinfo failed",
    r"name or service not known",
    r"temporary failure in name resolution",
    r"nodename nor servname provided",
    r"dns operation timed out",
    r"the resolution lifetime expired",
    r"timed out",
    r"timeout",
    r"network is unreachable",
    r"no route to host",
    r"connection aborted",
    r"connection reset",
    r"forcibly closed",
    r"unreachable",
    r"10054",  # WinError connection reset
    r"10051",  # network unreachable
    r"10060",  # connection timed out
    r"11001",  # WSAHOST_NOT_FOUND
    r"11002",  # WSATRY_AGAIN
)


def is_probe_failure(message: str | BaseException | None) -> bool:
    """Return True when an error likely comes from the local probe network."""
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
            "This looks like a local network/DNS/Wi‑Fi problem while scanning, "
            "not proof that the customer's site is broken. "
            "Retry on a stable connection before escalating."
        ),
        details={**(details or {}), "probe_failed": True},
    )
