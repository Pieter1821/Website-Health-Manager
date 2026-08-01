"""HTTP / HTTPS website availability checks."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import worst_status


def normalize_url(url: str) -> str:
    """Ensure the URL has a scheme so httpx can request it."""
    url = (url or "").strip().strip("\ufeff").strip("'\"")
    if not url:
        raise ValueError("Please enter a website address.")
    # Accept bare domains and full http(s) links the same way.
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Use a normal website link starting with http:// or https://")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or "." not in host:
        raise ValueError(
            "That doesn’t look like a website. Try something like mybusiness.co.za"
        )
    path = parsed.path or ""
    if path == "/":
        path = ""
    # Drop userinfo/query/fragment — we only need a clean site URL.
    return f"{scheme}://{host}{path}"


def check_website(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """
    Probe a website: status code, redirects, response time, redirect loops.

    Returns a dict with status, findings, response_time_ms, and raw details.
    """
    findings: list[Finding] = []
    target = normalize_url(url)
    started = time.perf_counter()
    redirect_history: list[str] = []
    final_url = target
    status_code: int | None = None
    error: str | None = None
    https_used = target.lower().startswith("https://")

    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            verify=True,
        ) as client:
            current = target
            for _ in range(10):
                response = client.request("GET", current)
                status_code = response.status_code
                redirect_history.append(f"{current} -> {status_code}")
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        findings.append(
                            Finding(
                                category="website",
                                title="Broken redirect",
                                status=FindingStatus.INCORRECT,
                                message="Redirect response missing Location header.",
                                recommendation="Fix the server redirect configuration.",
                            )
                        )
                        break
                    # Resolve relative redirects.
                    next_url = str(httpx.URL(current).join(location))
                    if next_url in [h.split(" -> ")[0] for h in redirect_history]:
                        findings.append(
                            Finding(
                                category="website",
                                title="Redirect loop",
                                status=FindingStatus.INCORRECT,
                                message=f"Detected redirect loop at {next_url}.",
                                recommendation="Remove circular redirects in DNS/CDN/app config.",
                                details={"history": redirect_history},
                            )
                        )
                        break
                    current = next_url
                    final_url = next_url
                    continue
                # Non-redirect response — done.
                final_url = str(response.url)
                https_used = final_url.lower().startswith("https://")
                break
            else:
                findings.append(
                    Finding(
                        category="website",
                        title="Too many redirects",
                        status=FindingStatus.INCORRECT,
                        message="Exceeded 10 redirects without a final response.",
                        recommendation="Simplify the redirect chain.",
                        details={"history": redirect_history},
                    )
                )
    except httpx.TimeoutException:
        error = f"Request timed out after {timeout}s"
    except httpx.ConnectError as exc:
        error = f"Connection failed: {exc}"
    except httpx.HTTPError as exc:
        error = f"HTTP error: {exc}"
    except Exception as exc:  # noqa: BLE001 — surface unexpected network issues
        error = f"Unexpected error: {exc}"

    elapsed_ms = (time.perf_counter() - started) * 1000

    if error:
        if is_probe_failure(error):
            findings.append(
                probe_failed_finding(
                    "website",
                    "Website check inconclusive",
                    error,
                    details={"url": target, "redirect_history": redirect_history},
                )
            )
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": findings,
                "response_time_ms": elapsed_ms,
                "raw": {
                    "url": target,
                    "error": error,
                    "probe_failed": True,
                    "redirect_history": redirect_history,
                },
            }
        findings.append(
            Finding(
                category="website",
                title="Website unreachable",
                status=FindingStatus.MISSING,
                message=error,
                recommendation="Check DNS, hosting, firewall, and whether the URL is correct.",
            )
        )
        return {
            "status": HealthStatus.CRITICAL,
            "findings": findings,
            "response_time_ms": elapsed_ms,
            "raw": {
                "url": target,
                "error": error,
                "redirect_history": redirect_history,
            },
        }

    assert status_code is not None
    if 200 <= status_code < 400:
        findings.append(
            Finding(
                category="website",
                title="Website online",
                status=FindingStatus.CORRECT,
                message=f"HTTP {status_code} in {elapsed_ms:.0f} ms (final: {final_url}).",
                details={
                    "status_code": status_code,
                    "final_url": final_url,
                    "redirects": redirect_history,
                },
            )
        )
        http_status = HealthStatus.HEALTHY
    elif 400 <= status_code < 500:
        findings.append(
            Finding(
                category="website",
                title="Client error response",
                status=FindingStatus.INCORRECT,
                message=f"HTTP {status_code} from {final_url}.",
                recommendation="Verify the path exists and authentication is not blocking probes.",
            )
        )
        http_status = HealthStatus.WARNING
    else:
        findings.append(
            Finding(
                category="website",
                title="Server error response",
                status=FindingStatus.INCORRECT,
                message=f"HTTP {status_code} from {final_url}.",
                recommendation="Investigate hosting / application errors.",
            )
        )
        http_status = HealthStatus.CRITICAL

    if https_used:
        findings.append(
            Finding(
                category="website",
                title="HTTPS enabled",
                status=FindingStatus.CORRECT,
                message="Final URL uses HTTPS.",
            )
        )
    else:
        findings.append(
            Finding(
                category="website",
                title="HTTPS not used",
                status=FindingStatus.INCORRECT,
                message="Site is reachable over HTTP only (or redirected to HTTP).",
                recommendation="Enable HTTPS and redirect HTTP → HTTPS.",
            )
        )
        http_status = worst_status([http_status, HealthStatus.WARNING])

    if elapsed_ms > 5000:
        findings.append(
            Finding(
                category="website",
                title="Slow response",
                status=FindingStatus.INCORRECT,
                message=f"Response took {elapsed_ms:.0f} ms.",
                recommendation="Investigate hosting performance or CDN configuration.",
            )
        )
        http_status = worst_status([http_status, HealthStatus.WARNING])

    return {
        "status": http_status,
        "findings": findings,
        "response_time_ms": elapsed_ms,
        "raw": {
            "url": target,
            "final_url": final_url,
            "status_code": status_code,
            "redirect_history": redirect_history,
            "https": https_used,
        },
    }
