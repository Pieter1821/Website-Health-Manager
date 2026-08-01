"""Hostname normalization and registrable-domain (eTLD+1) helpers."""

from __future__ import annotations

from urllib.parse import urlparse

# Multi-label public suffixes we care about (ZA + common ones).
# Keep this curated — unknown TLDs fall back to last-two-labels.
_MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.za",
        "org.za",
        "net.za",
        "web.za",
        "gov.za",
        "ac.za",
        "edu.za",
        "law.za",
        "mil.za",
        "nom.za",
        "school.za",
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "com.br",
        "co.jp",
    }
)


def strip_to_host(value: str) -> str:
    """Accept bare host, URL, or host:port — return host (no scheme/path)."""
    text = (value or "").strip().strip("\ufeff").strip("'\"")
    if not text:
        return ""
    if "://" not in text and "/" not in text and "?" not in text:
        host = text
    else:
        if "://" not in text:
            text = "https://" + text
        host = urlparse(text).hostname or ""
    return host.strip().lower().rstrip(".")


def split_host_port(value: str, default_port: int = 443) -> tuple[str, int]:
    """Return (hostname, port). Supports https://host:8443/path and host:8443."""
    text = (value or "").strip().strip("\ufeff").strip("'\"")
    if not text:
        return "", default_port
    port = default_port
    if "://" in text or "/" in text or "?" in text:
        if "://" not in text:
            text = "https://" + text
        parsed = urlparse(text)
        host = (parsed.hostname or "").strip().lower().rstrip(".")
        if parsed.port is not None:
            port = int(parsed.port)
        return host, port
    # Bare host or host:port (avoid IPv6 ambiguity — we only support names / IPv4 here).
    if text.count(":") == 1:
        host_part, port_part = text.rsplit(":", 1)
        if port_part.isdigit():
            return host_part.strip().lower().rstrip("."), int(port_part)
    return text.strip().lower().rstrip("."), port


def to_ascii_host(hostname: str) -> str:
    """IDN → punycode; ASCII hosts unchanged."""
    host = hostname.strip().lower().rstrip(".")
    if not host:
        return ""
    try:
        return host.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeEncodeError):
        return host


def normalize_hostname(value: str) -> str:
    """Canonical DNS hostname for checks (no scheme, lowercased, punycode)."""
    return to_ascii_host(strip_to_host(value))


def registrable_domain(hostname: str) -> str:
    """
    eTLD+1 style registrable domain for WHOIS/expiry.

    Examples:
      s1.thinaloans.co.za → thinaloans.co.za
      www.example.com → example.com
      thinaloans.co.za → thinaloans.co.za
    """
    host = normalize_hostname(hostname)
    if not host or "." not in host:
        return host
    labels = host.split(".")
    # Longest matching multi-label suffix wins.
    suffix_len = 1
    for size in range(min(len(labels) - 1, 4), 1, -1):
        candidate = ".".join(labels[-size:])
        if candidate in _MULTI_LABEL_SUFFIXES:
            suffix_len = size
            break
    need = suffix_len + 1
    if len(labels) <= need:
        return host
    return ".".join(labels[-need:])
