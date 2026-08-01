"""DNS snapshot diff tests."""

from whm.domain.models import DnsRecord
from whm.infrastructure.dns_checker import diff_dns_records


def test_diff_detects_added_and_removed():
    old = [DnsRecord("A", "example.com", "1.2.3.4")]
    new = [
        DnsRecord("A", "example.com", "9.9.9.9"),
        DnsRecord("MX", "example.com", "mail.example.com", priority=10),
    ]
    changes = diff_dns_records(old, new)
    kinds = {(c["change"], c["rtype"]) for c in changes}
    assert ("removed", "A") in kinds
    assert ("added", "A") in kinds
    assert ("added", "MX") in kinds
