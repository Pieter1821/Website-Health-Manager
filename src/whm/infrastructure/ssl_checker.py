"""SSL/TLS certificate inspection."""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from typing import Any

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import ExtensionOID, NameOID

from whm.domain.models import Finding, FindingStatus, HealthStatus
from whm.domain.probe import is_probe_failure, probe_failed_finding
from whm.domain.status import days_to_status, worst_status


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


def _hostname_matches(hostname: str, sans: list[str], subject_cn: str | None) -> bool:
    candidates = list(sans)
    if subject_cn:
        candidates.append(subject_cn)
    host = hostname.lower().rstrip(".")
    for name in candidates:
        pattern = name.lower().rstrip(".")
        if pattern.startswith("*."):
            # Wildcard: *.example.com matches a.example.com, not example.com
            suffix = pattern[1:]  # ".example.com"
            if host.endswith(suffix) and host.count(".") == pattern.count("."):
                return True
        elif host == pattern:
            return True
    return False


def check_ssl(hostname: str, port: int = 443, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch and evaluate the TLS certificate for hostname:port."""
    findings: list[Finding] = []
    hostname = hostname.strip().lower().rstrip(".")

    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                der = ssock.getpeercert(binary_form=True)
                tls_version = ssock.version()
                cipher = ssock.cipher()
        assert der is not None
        cert = _parse_cert(der)
    except ssl.SSLCertVerificationError as exc:
        return {
            "status": HealthStatus.CRITICAL,
            "findings": [
                Finding(
                    category="ssl",
                    title="Certificate validation failed",
                    status=FindingStatus.INCORRECT,
                    message=str(exc),
                    recommendation="Install a valid certificate from a trusted CA; check hostname and chain.",
                )
            ],
            "raw": {"hostname": hostname, "error": str(exc)},
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
            "raw": {"hostname": hostname, "error": "timeout", "probe_failed": True},
        }
    except OSError as exc:
        if is_probe_failure(exc):
            return {
                "status": HealthStatus.UNKNOWN,
                "findings": [
                    probe_failed_finding(
                        "ssl",
                        "SSL check inconclusive",
                        str(exc),
                    )
                ],
                "raw": {"hostname": hostname, "error": str(exc), "probe_failed": True},
            }
        return {
            "status": HealthStatus.CRITICAL,
            "findings": [
                Finding(
                    category="ssl",
                    title="SSL connection failed",
                    status=FindingStatus.MISSING,
                    message=str(exc),
                    recommendation="Verify the host resolves and port 443 is open.",
                )
            ],
            "raw": {"hostname": hostname, "error": str(exc)},
        }

    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    now = datetime.now(timezone.utc)
    days_remaining = (not_after - now).days

    issuer = _name_as_dict(cert.issuer)
    subject = _name_as_dict(cert.subject)
    subject_cn = subject.get("commonName")
    try:
        subject_cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value  # type: ignore[assignment]
    except IndexError:
        subject_cn = subject.get("commonName")

    sans = _get_sans(cert)
    is_wildcard = any(s.startswith("*.") for s in sans) or (
        isinstance(subject_cn, str) and subject_cn.startswith("*.")
    )
    hostname_ok = _hostname_matches(hostname, sans, subject_cn if isinstance(subject_cn, str) else None)

    # Self-signed heuristic: issuer == subject
    self_signed = cert.issuer == cert.subject

    statuses: list[HealthStatus] = [days_to_status(days_remaining)]

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
        findings.append(
            Finding(
                category="ssl",
                title="Hostname match",
                status=FindingStatus.CORRECT,
                message=f"Certificate covers {hostname}.",
                details={"sans": sans, "cn": subject_cn},
            )
        )
    else:
        findings.append(
            Finding(
                category="ssl",
                title="Hostname mismatch",
                status=FindingStatus.INCORRECT,
                message=f"Certificate does not cover {hostname}.",
                recommendation="Issue a certificate that includes this hostname in SAN.",
                details={"sans": sans, "cn": subject_cn},
            )
        )
        statuses.append(HealthStatus.CRITICAL)

    if self_signed:
        findings.append(
            Finding(
                category="ssl",
                title="Self-signed certificate",
                status=FindingStatus.INCORRECT,
                message="Issuer matches subject (self-signed).",
                recommendation="Replace with a publicly trusted certificate (Let's Encrypt, commercial CA).",
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
                message="Certificate includes a wildcard name.",
                details={"sans": sans},
            )
        )

    return {
        "status": worst_status(statuses),
        "findings": findings,
        "raw": {
            "hostname": hostname,
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
        },
    }
