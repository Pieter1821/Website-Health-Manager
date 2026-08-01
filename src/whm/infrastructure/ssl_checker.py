"""SSL/TLS certificate inspection (SNI, wildcards, chain trust, CDN labeling)."""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from typing import Any, Optional

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import ExtensionOID, NameOID

from whm.domain.hostnames import normalize_hostname, split_host_port
from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import days_to_status, worst_status

_CDN_ISSUER_MARKERS = (
    "cloudflare",
    "cloudfront",
    "akamai",
    "fastly",
    "incapsula",
    "sucuri",
    "imperva",
    "keycdn",
)


def _parse_cert(der_bytes: bytes) -> x509.Certificate:
    return x509.load_der_x509_certificate(der_bytes, default_backend())


def _name_as_dict(name: x509.Name) -> dict[str, str]:
    result: dict[str, str] = {}
    for attr in name:
        result[attr.oid._name] = attr.value  # type: ignore[assignment]
    return result


def _get_sans(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        return ext.value.get_values_for_type(x509.DNSName)  # type: ignore[attr-defined]
    except x509.ExtensionNotFound:
        return []


def hostname_matches(hostname: str, sans: list[str], subject_cn: str | None) -> bool:
    """Exact SAN/CN match or single-label wildcard (*.example.com → a.example.com)."""
    candidates = list(sans)
    if subject_cn:
        candidates.append(subject_cn)
    host = normalize_hostname(hostname)
    for name in candidates:
        pattern = name.lower().rstrip(".")
        if pattern.startswith("*."):
            # RFC 6125: *.a.b matches one label left of a.b, not a.b itself.
            suffix = pattern[1:]  # ".example.com"
            if (
                host.endswith(suffix)
                and host != suffix.lstrip(".")
                and host.count(".") == pattern.count(".")
            ):
                return True
        elif host == pattern:
            return True
    return False


def _issuer_looks_like_cdn(issuer: dict[str, str]) -> Optional[str]:
    blob = " ".join(str(v) for v in issuer.values()).lower()
    for marker in _CDN_ISSUER_MARKERS:
        if marker in blob:
            return marker
    return None


def _fetch_peer_cert(
    hostname: str,
    port: int,
    timeout: float,
    *,
    verify: bool,
) -> tuple[bytes, str | None, tuple[Any, ...] | None]:
    """
    Connect with SNI (server_hostname=hostname). Never connect by IP alone.
    When verify=False, still send SNI so we inspect the name-based cert.
    """
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((hostname, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            der = ssock.getpeercert(binary_form=True)
            tls_version = ssock.version()
            cipher = ssock.cipher()
    if der is None:
        raise OSError("No peer certificate returned")
    return der, tls_version, cipher


def check_ssl(hostname: str, port: int = 443, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch and evaluate the TLS certificate for hostname:port using SNI."""
    host, parsed_port = split_host_port(hostname, default_port=port)
    if parsed_port != 443 or ":" in (hostname or ""):
        port = parsed_port
    hostname = normalize_hostname(host)
    if not hostname:
        return {
            "status": HealthStatus.UNKNOWN,
            "findings": [
                Finding(
                    category="ssl",
                    title="SSL check skipped",
                    status=FindingStatus.INCONCLUSIVE,
                    message="No hostname to check.",
                )
            ],
            "raw": {"hostname": "", "error": "empty hostname"},
        }

    findings: list[Finding] = []
    verified = True
    verify_error: str | None = None
    der: bytes
    tls_version: str | None
    cipher: tuple[Any, ...] | None

    try:
        der, tls_version, cipher = _fetch_peer_cert(
            hostname, port, timeout, verify=True
        )
    except ssl.SSLCertVerificationError as exc:
        verified = False
        verify_error = str(exc)
        try:
            der, tls_version, cipher = _fetch_peer_cert(
                hostname, port, timeout, verify=False
            )
        except Exception:  # noqa: BLE001
            return {
                "status": HealthStatus.CRITICAL,
                "findings": [
                    Finding(
                        category="ssl",
                        title="Certificate validation failed",
                        status=FindingStatus.INCORRECT,
                        message=str(exc),
                        recommendation=(
                            "Install a valid certificate from a trusted CA; "
                            "check hostname, expiry, and the full certificate chain."
                        ),
                    )
                ],
                "raw": {"hostname": hostname, "port": port, "error": str(exc)},
            }
    except (socket.timeout, TimeoutError) as exc:
        return {
            "status": HealthStatus.UNKNOWN,
            "findings": [
                probe_failed_finding(
                    "ssl",
                    "SSL check inconclusive",
                    f"Timed out connecting to {hostname}:{port}: {exc}",
                )
            ],
            "raw": {
                "hostname": hostname,
                "port": port,
                "error": "timeout",
                "probe_failed": True,
            },
        }
    except OSError as exc:
        if is_probe_failure(exc):
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": [
                    probe_failed_finding("ssl", "SSL check inconclusive", str(exc))
                ],
                "raw": {
                    "hostname": hostname,
                    "port": port,
                    "error": str(exc),
                    "probe_failed": True,
                },
            }
        return {
            "status": HealthStatus.CRITICAL,
            "findings": [
                Finding(
                    category="ssl",
                    title="SSL connection failed",
                    status=FindingStatus.MISSING,
                    message=str(exc),
                    recommendation="Verify the host resolves and the HTTPS port is open.",
                )
            ],
            "raw": {"hostname": hostname, "port": port, "error": str(exc)},
        }

    cert = _parse_cert(der)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    now = datetime.now(timezone.utc)
    days_remaining = (not_after - now).days

    issuer = _name_as_dict(cert.issuer)
    subject = _name_as_dict(cert.subject)
    try:
        subject_cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except IndexError:
        subject_cn = subject.get("commonName")
    subject_cn_str = subject_cn if isinstance(subject_cn, str) else None

    sans = _get_sans(cert)
    is_wildcard = any(s.startswith("*.") for s in sans) or (
        isinstance(subject_cn_str, str) and subject_cn_str.startswith("*.")
    )
    hostname_ok = hostname_matches(hostname, sans, subject_cn_str)
    self_signed = cert.issuer == cert.subject
    cdn_marker = _issuer_looks_like_cdn(issuer)

    statuses: list[HealthStatus] = [days_to_status(days_remaining)]

    if not verified:
        findings.append(
            Finding(
                category="ssl",
                title="Certificate chain / trust failed",
                status=FindingStatus.INCORRECT,
                message=verify_error or "Browser-trusted validation failed.",
                recommendation=(
                    "Fix the certificate chain (install the intermediate CA), "
                    "replace an expired or revoked cert, or use a publicly trusted CA. "
                    "This is separate from the expiry date below."
                ),
                details={"verify_error": verify_error},
            )
        )
        statuses.append(HealthStatus.CRITICAL)

    findings.append(
        Finding(
            category="ssl",
            title="Certificate expiry",
            status=(
                FindingStatus.CORRECT
                if days_remaining > 30
                else FindingStatus.INCORRECT
                if days_remaining >= 0
                else FindingStatus.MISSING
            ),
            message=f"Expires {not_after.date().isoformat()} ({days_remaining} days remaining).",
            recommendation="Renew the certificate before expiry (aim for >30 days buffer).",
            details={
                "not_before": not_before.isoformat(),
                "not_after": not_after.isoformat(),
                "days_remaining": days_remaining,
            },
        )
    )

    if hostname_ok:
        cover = "wildcard SAN" if is_wildcard else "SAN/CN"
        findings.append(
            Finding(
                category="ssl",
                title="Hostname match",
                status=FindingStatus.CORRECT,
                message=f"Certificate covers {hostname} ({cover}).",
                details={"sans": sans, "cn": subject_cn_str, "matched_via_wildcard": is_wildcard},
            )
        )
    else:
        findings.append(
            Finding(
                category="ssl",
                title="Hostname mismatch",
                status=FindingStatus.INCORRECT,
                message=f"Certificate does not cover {hostname} (checked SANs with wildcard rules).",
                recommendation="Issue a certificate that includes this hostname or a matching wildcard SAN.",
                details={"sans": sans, "cn": subject_cn_str},
            )
        )
        statuses.append(HealthStatus.CRITICAL)

    if self_signed:
        findings.append(
            Finding(
                category="ssl",
                title="Not trusted (self-signed)",
                status=FindingStatus.INCORRECT,
                message="Self-signed certificate — browsers will warn visitors.",
                recommendation="Replace with a publicly trusted certificate (Let's Encrypt or commercial CA).",
            )
        )
        statuses.append(HealthStatus.WARNING)
    else:
        findings.append(
            Finding(
                category="ssl",
                title="Certificate issuer",
                status=FindingStatus.CORRECT,
                message=f"Issued by {issuer.get('organizationName') or issuer.get('commonName') or 'unknown'}.",
                details={"issuer": issuer},
            )
        )

    if cdn_marker:
        findings.append(
            Finding(
                category="ssl",
                title="CDN / proxy certificate",
                status=FindingStatus.INFO,
                message=(
                    f"This looks like an edge certificate ({cdn_marker}). "
                    "WHM checked what visitors hit at the proxy — the origin server "
                    "behind the CDN was not checked separately."
                ),
                recommendation=(
                    "If you need origin SSL health, check the origin host directly "
                    "or in the CDN dashboard."
                ),
                details={"cdn": cdn_marker},
            )
        )

    if tls_version in {"TLSv1", "TLSv1.1", None}:
        findings.append(
            Finding(
                category="ssl",
                title="Weak TLS version",
                status=FindingStatus.INCORRECT,
                message=f"Negotiated {tls_version}.",
                recommendation="Disable TLS 1.0/1.1; require TLS 1.2+.",
            )
        )
        statuses.append(HealthStatus.WARNING)
    else:
        findings.append(
            Finding(
                category="ssl",
                title="TLS version",
                status=FindingStatus.CORRECT,
                message=f"Negotiated {tls_version}.",
                details={"cipher": cipher},
            )
        )

    if is_wildcard:
        findings.append(
            Finding(
                category="ssl",
                title="Wildcard certificate",
                status=FindingStatus.INFO,
                message="Certificate includes a wildcard name (valid for matching subdomains).",
                details={"sans": sans},
            )
        )

    return {
        "status": worst_status(statuses),
        "findings": findings,
        "raw": {
            "hostname": hostname,
            "port": port,
            "sni": hostname,
            "verified": verified,
            "verify_error": verify_error,
            "issuer": issuer,
            "subject": subject,
            "sans": sans,
            "not_before": not_before.isoformat(),
            "not_after": not_after.isoformat(),
            "days_remaining": days_remaining,
            "tls_version": tls_version,
            "cipher": cipher,
            "self_signed": self_signed,
            "wildcard": is_wildcard,
            "cdn_edge": cdn_marker,
        },
    }
