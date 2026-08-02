"""Regression tests: subdomain SSL matching, registrable domain, .co.za WHOIS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from whm.domain.hostnames import (
    normalize_hostname,
    registrable_domain,
    split_host_port,
    strip_to_host,
)
from whm.domain.models import FindingStatus, HealthStatus
from whm.infrastructure.ssl_checker import check_ssl, hostname_matches
from whm.infrastructure.whois_checker import check_domain


def test_normalize_strips_scheme_trailing_dot_and_case():
    assert normalize_hostname("HTTPS://S1.ThinaLoans.co.za./path") == "s1.thinaloans.co.za"
    assert strip_to_host("s1.thinaloans.co.za.") == "s1.thinaloans.co.za"


def test_split_host_port_from_url():
    host, port = split_host_port("https://shop.example.com:8443/login")
    assert host == "shop.example.com"
    assert port == 8443


def test_split_host_port_bare_and_empty():
    assert split_host_port("host.example:8443") == ("host.example", 8443)
    assert split_host_port("") == ("", 443)


def test_idn_to_punycode():
    assert "xn--" in normalize_hostname("münchen.example")


def test_registrable_domain_co_za_subdomain():
    assert registrable_domain("s1.thinaloans.co.za") == "thinaloans.co.za"
    assert registrable_domain("thinaloans.co.za") == "thinaloans.co.za"
    assert registrable_domain("www.example.com") == "example.com"
    assert registrable_domain("a.b.example.com") == "example.com"
    assert registrable_domain("shop.example.co.uk") == "example.co.uk"
    assert registrable_domain("lonely") == "lonely"


def test_wildcard_san_matches_subdomain_not_apex():
    sans = ["*.thinaloans.co.za"]
    assert hostname_matches("s1.thinaloans.co.za", sans, None)
    assert hostname_matches("www.thinaloans.co.za", sans, None)
    assert not hostname_matches("thinaloans.co.za", sans, None)
    assert not hostname_matches("a.b.thinaloans.co.za", sans, None)


def test_explicit_san_match():
    assert hostname_matches("mail.example.com", ["mail.example.com", "www.example.com"], None)
    assert not hostname_matches("other.example.com", ["mail.example.com"], None)


def test_whois_uses_registrable_domain_for_subdomain():
    data = MagicMock()
    data.domain_name = "thinaloans.co.za"
    data.expiration_date = datetime.now(timezone.utc) + timedelta(days=200)
    data.creation_date = None
    data.updated_date = None
    data.registrar = "Test Registrar"
    data.status = None
    with patch(
        "whm.infrastructure.whois_checker._whois_lookup", return_value=data
    ) as mocked:
        result = check_domain("s1.thinaloans.co.za")
    mocked.assert_called_once_with("thinaloans.co.za")
    assert result["raw"]["queried_domain"] == "thinaloans.co.za"
    assert result["raw"]["domain"] == "s1.thinaloans.co.za"
    assert result["status"] == HealthStatus.HEALTHY
    assert any("subdomain" in f.message.lower() for f in result["findings"])


def test_whois_empty_co_za_is_unknown_not_guessed():
    empty = MagicMock()
    empty.domain_name = None
    empty.expiration_date = None
    empty.registrar = None
    with patch("whm.infrastructure.whois_checker._whois_lookup", return_value=empty):
        result = check_domain("thinaloans.co.za")
    assert result["status"] == HealthStatus.UNKNOWN
    assert result["raw"].get("expiration_date") is None
    assert any(f.title == "Domain expiry unknown" for f in result["findings"])


def test_whois_lookup_does_not_require_public_suffix_list(monkeypatch):
    """Frozen builds often lack whois/data/public_suffix_list.dat — still must work."""
    from whm.infrastructure import whois_checker

    class FakeNIC:
        def whois_lookup(self, *a, **k):
            return "Domain Name: EXAMPLE.COM\nRegistrar: Example Registrar\nRegistry Expiry Date: 2027-06-01T00:00:00Z\n"

    class FakeEntry(dict):
        def __getattr__(self, item):
            try:
                return self[item]
            except KeyError as exc:
                raise AttributeError(item) from exc

    def fake_load(domain, text):
        return FakeEntry(
            domain_name=domain,
            expiration_date=datetime(2027, 6, 1, tzinfo=timezone.utc),
            creation_date=None,
            updated_date=None,
            registrar="Example Registrar",
            status=None,
        )

    monkeypatch.setattr(whois_checker, "NICClient", FakeNIC)
    monkeypatch.setattr(whois_checker.WhoisEntry, "load", staticmethod(fake_load))
    result = check_domain("www.example.com")
    assert result["status"] == HealthStatus.HEALTHY
    assert result["raw"]["queried_domain"] == "example.com"
    assert result["raw"]["expiration_date"] is not None


def test_dangling_cname_is_critical_finding():
    import dns.resolver
    from whm.domain.models import DnsRecord
    from whm.infrastructure.dns_checker import _dangling_cname_findings

    resolver = MagicMock()
    resolver.resolve.side_effect = dns.resolver.NXDOMAIN()
    with patch(
        "whm.infrastructure.dns_checker._make_resolver",
        return_value=resolver,
    ):
        findings = _dangling_cname_findings(
            [DnsRecord(rtype="CNAME", name="old.example.com", value="gone.herokuapp.com")],
            nameserver=None,
            timeout=1.0,
        )
    assert len(findings) == 1
    assert findings[0].title.startswith("Dangling CNAME")
    assert findings[0].status == FindingStatus.MISSING


def test_ssl_sni_passed_as_server_hostname():
    """Ensure wrap_socket is called with server_hostname=exact host (SNI)."""
    import ssl as ssl_mod

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getpeercert(self, binary_form=False):
            # Minimal will fail parse — we only assert SNI wiring via wrap_socket kwargs.
            raise ssl_mod.SSLError("stop after wrap")

        def version(self):
            return "TLSv1.3"

        def cipher(self):
            return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

    wrapped = FakeSock()
    context = MagicMock()
    context.wrap_socket.return_value = wrapped

    with (
        patch("whm.infrastructure.ssl_checker.ssl.create_default_context", return_value=context),
        patch("whm.infrastructure.ssl_checker.socket.create_connection", return_value=FakeSock()),
    ):
        result = check_ssl("s1.thinaloans.co.za", timeout=1)

    context.wrap_socket.assert_called()
    kwargs = context.wrap_socket.call_args.kwargs
    assert kwargs.get("server_hostname") == "s1.thinaloans.co.za"
    # Connection failed after SNI wrap — still must not crash.
    assert result["status"] in {HealthStatus.CRITICAL, HealthStatus.UNKNOWN}
