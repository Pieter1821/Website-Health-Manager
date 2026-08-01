"""Unit tests for SPF / DMARC / DKIM parsers (no network)."""

from whm.domain.models import FindingStatus
from whm.infrastructure.email_checker import check_dkim, check_dmarc, parse_spf


def test_parse_spf_missing():
    result = parse_spf(["v=somethingelse", "hello"])
    assert any(f.status == FindingStatus.MISSING for f in result["findings"])


def test_parse_spf_duplicate():
    result = parse_spf(
        [
            "v=spf1 include:sendgrid.net ~all",
            "v=spf1 include:other.com -all",
        ]
    )
    assert any(f.title == "Duplicate SPF" for f in result["findings"])


def test_parse_spf_valid_with_sendgrid():
    result = parse_spf(["v=spf1 include:sendgrid.net ~all"])
    assert result["lookup_count"] >= 1
    assert any(f.status == FindingStatus.CORRECT and "exists" in f.title.lower() for f in result["findings"])


def test_parse_spf_lookup_limit():
    # 11 include: mechanisms exceed the soft limit.
    mechanisms = " ".join(f"include:a{i}.example.com" for i in range(11))
    result = parse_spf([f"v=spf1 {mechanisms} -all"])
    assert any("lookup limit" in f.title.lower() for f in result["findings"])


def _ok_txt(records):
    return lambda *a, **k: {"probe_ok": True, "records": records, "error": None}


def test_dmarc_missing_uses_network_stub(monkeypatch):
    from whm.infrastructure import email_checker

    monkeypatch.setattr(email_checker, "_txt_lookup", _ok_txt([]))
    result = check_dmarc("example.com")
    assert any(f.status == FindingStatus.MISSING for f in result["findings"])


def test_dmarc_policy_none(monkeypatch):
    from whm.infrastructure import email_checker

    monkeypatch.setattr(
        email_checker,
        "_txt_lookup",
        _ok_txt(["v=DMARC1; p=none; rua=mailto:a@b.com"]),
    )
    result = check_dmarc("example.com")
    titles = {f.title: f.status for f in result["findings"]}
    assert titles["DMARC record exists"] == FindingStatus.CORRECT
    assert titles["DMARC policy"] == FindingStatus.INCORRECT


def test_dmarc_policy_reject(monkeypatch):
    from whm.infrastructure import email_checker

    monkeypatch.setattr(
        email_checker,
        "_txt_lookup",
        _ok_txt(["v=DMARC1; p=reject; rua=mailto:a@b.com; pct=100"]),
    )
    result = check_dmarc("example.com")
    policy = next(f for f in result["findings"] if f.title == "DMARC policy")
    assert policy.status == FindingStatus.CORRECT


def test_dmarc_probe_failure_is_inconclusive(monkeypatch):
    from whm.infrastructure import email_checker

    monkeypatch.setattr(
        email_checker,
        "_txt_lookup",
        lambda *a, **k: {
            "probe_ok": False,
            "records": [],
            "error": "The resolution lifetime expired",
        },
    )
    result = check_dmarc("example.com")
    assert result["probe_ok"] is False
    assert result["findings"][0].status == FindingStatus.INCONCLUSIVE


def test_dmarc_policy_none_explains_monitor_only(monkeypatch):
    from whm.infrastructure import email_checker

    monkeypatch.setattr(
        email_checker,
        "_txt_lookup",
        _ok_txt(["v=DMARC1; p=none; rua=mailto:a@b.com"]),
    )
    result = check_dmarc("example.com")
    policy = next(f for f in result["findings"] if f.title == "DMARC policy")
    assert "monitor" in policy.message.lower() or "reports" in policy.message.lower()
    assert "quarantine" in (policy.recommendation or "").lower()


def test_dkim_all_missing_collapses_to_one_finding(monkeypatch):
    from whm.infrastructure import email_checker

    monkeypatch.setattr(email_checker, "_txt_lookup", _ok_txt([]))
    result = check_dkim("example.com", ["s1", "s2", "em", "default"])
    missing = [f for f in result["findings"] if f.status == FindingStatus.MISSING]
    assert len(missing) == 1
    assert missing[0].title == "DKIM not found on common selectors"
    assert "still send" in missing[0].message.lower()
    assert "email provider" in (missing[0].recommendation or "").lower()


def test_dkim_one_found_downgrades_other_missing(monkeypatch):
    from whm.infrastructure import email_checker

    def fake_txt(name, *a, **k):
        if name.startswith("s1."):
            return {
                "probe_ok": True,
                "records": ["v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA"],
                "error": None,
            }
        return {"probe_ok": True, "records": [], "error": None}

    monkeypatch.setattr(email_checker, "_txt_lookup", fake_txt)
    result = check_dkim("example.com", ["s1", "s2"])
    assert result["found_selectors"] == ["s1"]
    assert not any(f.status == FindingStatus.MISSING for f in result["findings"])
    assert any(
        f.status == FindingStatus.INFO and "s2" in f.title
        for f in result["findings"]
    )


def test_website_only_domain_skips_email_homework(monkeypatch):
    from whm.domain.models import HealthStatus
    from whm.infrastructure import email_checker
    from whm.infrastructure.email_checker import check_email

    monkeypatch.setattr(email_checker, "_txt_lookup", _ok_txt([]))
    monkeypatch.setattr(
        email_checker,
        "check_mx",
        lambda *a, **k: {"findings": [], "records": [], "probe_ok": True},
    )
    result = check_email("brochure.example", probe_smtp=False)
    assert result["status"] == HealthStatus.HEALTHY
    assert result["raw"].get("mail_active") is False
    assert any("not used" in f.title.lower() for f in result["findings"])
    assert not any(f.status == FindingStatus.MISSING for f in result["findings"])


def test_www_host_checks_registrable_domain_for_email(monkeypatch):
    """www.example.com must not be judged for SPF/DKIM/DMARC/MX on the www name."""
    from whm.domain.models import HealthStatus
    from whm.infrastructure import email_checker
    from whm.infrastructure.email_checker import check_email

    looked_up: list[str] = []

    def fake_txt(name, *a, **k):
        looked_up.append(name)
        if name == "example.com":
            return _ok_txt(["v=spf1 include:_spf.google.com ~all"])(name)
        if name.startswith("_dmarc."):
            return _ok_txt(["v=DMARC1; p=reject; rua=mailto:a@b.com"])(name)
        if "._domainkey." in name:
            return _ok_txt([])(name)
        return _ok_txt([])(name)

    mx_domains: list[str] = []

    def fake_mx(domain, **k):
        mx_domains.append(domain)
        return {
            "findings": [],
            "records": [type("R", (), {"value": "aspmx.l.google.com", "priority": 1})()],
            "probe_ok": True,
        }

    monkeypatch.setattr(email_checker, "_txt_lookup", fake_txt)
    monkeypatch.setattr(email_checker, "check_mx", fake_mx)
    monkeypatch.setattr(email_checker, "check_sendgrid", lambda *a, **k: [])

    result = check_email("www.example.com", probe_smtp=False)
    assert result["raw"]["input_host"] == "www.example.com"
    assert result["raw"]["queried_domain"] == "example.com"
    assert mx_domains == ["example.com"]
    assert "example.com" in looked_up
    assert "www.example.com" not in looked_up
    assert not any(name.endswith(".www.example.com") for name in looked_up)
    assert result["status"] != HealthStatus.UNKNOWN
    assert any(
        f.category == "spf" and f.status == FindingStatus.CORRECT for f in result["findings"]
    )


def test_sendgrid_skipped_when_no_hints(monkeypatch):
    from whm.infrastructure import email_checker
    from whm.infrastructure.email_checker import check_sendgrid

    monkeypatch.setattr(email_checker, "_sendgrid_cname_selectors", lambda *a, **k: [])
    findings = check_sendgrid(
        "example.com",
        spf_records=["v=spf1 include:_spf.google.com ~all"],
        dkim_found=[],
    )
    assert findings == []


def test_sendgrid_reports_missing_dkim_when_spf_has_include(monkeypatch):
    from whm.infrastructure import email_checker
    from whm.infrastructure.email_checker import check_sendgrid

    monkeypatch.setattr(email_checker, "_sendgrid_cname_selectors", lambda *a, **k: [])
    findings = check_sendgrid(
        "example.com",
        spf_records=["v=spf1 include:sendgrid.net ~all"],
        dkim_found=[],
    )
    titles = {f.title: f.status for f in findings}
    assert titles["SendGrid SPF include"] == FindingStatus.CORRECT
    assert titles["SendGrid DKIM"] == FindingStatus.MISSING
