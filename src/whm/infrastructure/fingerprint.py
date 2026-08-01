"""Hosting and technology detection (Phase 4)."""

from __future__ import annotations

import re
from typing import Any

import httpx

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.infrastructure.http_checker import normalize_url

HOSTING_HINTS = (
    ("cloudflare", ("cf-ray", "cloudflare"), r"cloudflare"),
    ("aws", ("x-amz-cf-id", "x-amz-request-id"), r"amazonaws|awselb"),
    ("azure", ("x-azure-ref", "x-msedge-ref"), r"azure|microsoftonline"),
    ("vercel", ("x-vercel-id",), r"vercel"),
    ("netlify", ("x-nf-request-id",), r"netlify"),
    ("digitalocean", (), r"digitalocean"),
)

SERVER_HINTS = (
    ("nginx", r"nginx"),
    ("apache", r"apache"),
    ("iis", r"microsoft-iis|iis"),
)

TECH_HINTS = (
    ("WordPress", r"wp-content|wordpress"),
    ("Next.js", r"_next/static|next-js"),
    ("React", r"react|data-reactroot"),
    ("Angular", r"ng-version|angular"),
    ("Vue", r"__vue__|vue\.js"),
    ("ASP.NET", r"asp\.net|__viewstate"),
    ("Laravel", r"laravel_session"),
    ("PHP", r"\.php\b|x-powered-by:\s*php"),
    ("Node.js", r"express|x-powered-by:\s*express"),
)


def detect_stack(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Best-effort hosting / server / technology detection from headers + HTML."""
    target = normalize_url(url)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=True) as client:
            response = client.get(target)
        headers = {k.lower(): v for k, v in response.headers.items()}
        body = response.text[:200_000]
        blob = "\n".join(f"{k}:{v}" for k, v in headers.items()) + "\n" + body
    except Exception as exc:  # noqa: BLE001
        if is_probe_failure(exc):
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": [
                    probe_failed_finding("hosting", "Hosting check inconclusive", str(exc))
                ],
                "raw": {"probe_failed": True},
            }
        return {
            "status": HealthStatus.UNKNOWN,
            "findings": [
                Finding(
                    category="hosting",
                    title="Could not detect hosting",
                    status=FindingStatus.INFO,
                    message=str(exc),
                )
            ],
            "raw": {"error": str(exc)},
        }

    findings: list[Finding] = []
    hosting = "Unknown"
    for name, header_keys, pattern in HOSTING_HINTS:
        if any(h in headers for h in header_keys) or re.search(pattern, blob, re.I):
            hosting = name.upper() if name == "aws" else name.title()
            break

    server = headers.get("server", "Unknown")
    for name, pattern in SERVER_HINTS:
        if re.search(pattern, server, re.I) or re.search(pattern, blob, re.I):
            server = name.upper() if name == "iis" else name.title()
            break

    techs: list[str] = []
    for name, pattern in TECH_HINTS:
        if re.search(pattern, blob, re.I):
            techs.append(name)

    findings.append(
        Finding(
            category="hosting",
            title="Likely hosting / CDN",
            status=FindingStatus.INFO,
            message=hosting,
        )
    )
    findings.append(
        Finding(
            category="hosting",
            title="Web server",
            status=FindingStatus.INFO,
            message=str(server),
        )
    )
    findings.append(
        Finding(
            category="technology",
            title="Detected technology",
            status=FindingStatus.INFO,
            message=", ".join(techs) if techs else "Not clearly detected",
            details={"technologies": techs},
        )
    )
    return {
        "status": HealthStatus.HEALTHY,
        "findings": findings,
        "raw": {"hosting": hosting, "server": server, "technologies": techs},
    }
