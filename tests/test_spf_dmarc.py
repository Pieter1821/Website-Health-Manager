"""Unit tests for SPF / DMARC parsers (no network)."""

from whm.domain.models import FindingStatus
from whm.infrastructure.email_checker import parse_spf
from whm.infrastructure.email_checker import check_dmarc


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
