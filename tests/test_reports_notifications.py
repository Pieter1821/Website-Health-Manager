"""Report + notification helper tests (no network)."""

from pathlib import Path

from whm.domain.models import (
    Finding,
    FindingStatus,
    HealthCheckResult,
    HealthStatus,
    RiskLevel,
    Website,
)
from whm.infrastructure.notifications import format_message, should_notify
from whm.infrastructure.reports import (
    build_report_bundle,
    export_csv,
    export_html,
    export_json,
)


def _sample():
    site = Website(
        url="https://example.com",
        domain="example.com",
        display_name="Example",
        id=1,
    )
    result = HealthCheckResult(
        website_id=1,
        overall_status=HealthStatus.CRITICAL,
        risk_level=RiskLevel.HIGH,
        website_status=HealthStatus.HEALTHY,
        ssl_status=HealthStatus.HEALTHY,
        domain_status=HealthStatus.UNKNOWN,
        dns_status=HealthStatus.HEALTHY,
        email_status=HealthStatus.CRITICAL,
        findings=[
            Finding("spf", "SPF missing", FindingStatus.MISSING, "none", "Add SPF"),
        ],
    )
    return site, result


def test_should_notify_levels():
    _, result = _sample()
    assert should_notify(result, "critical")
    assert should_notify(result, "warning")
    assert should_notify(result, "always")
    assert not should_notify(result, "never")


def test_format_message_plain():
    site, result = _sample()
    text = format_message(site, result)
    assert "Example" in text
    assert "wrong" in text.lower() or "Something" in text


def test_exports(tmp_path: Path):
    site, result = _sample()
    j = export_json(tmp_path / "r.json", site, result)
    c = export_csv(tmp_path / "r.csv", site, result)
    h = export_html(tmp_path / "r.html", site, result)
    assert j.exists() and "spf" in j.read_text(encoding="utf-8")
    assert c.exists() and "What to do" in c.read_text(encoding="utf-8")
    assert h.exists() and "Know why it broke" in h.read_text(encoding="utf-8")


def test_build_report_bundle_zip():
    import zipfile
    from io import BytesIO

    site, result = _sample()
    filename, payload = build_report_bundle(site, result)
    assert filename.endswith("-report.zip")
    assert payload[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        assert any(n.endswith(".html") for n in names)
        assert any(n.endswith(".csv") for n in names)
        assert any(n.endswith(".json") for n in names)
        html = next(n for n in names if n.endswith(".html"))
        assert "Example" in archive.read(html).decode("utf-8")
