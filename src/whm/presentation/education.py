"""Short educational blurbs shown in the detail view."""

EDUCATION = {
    "website": (
        "Website checks confirm the site responds over HTTP/HTTPS, follows redirects "
        "safely, and returns a usable status code."
    ),
    "ssl": (
        "SSL/TLS certificates encrypt traffic and prove hostname ownership. Browsers "
        "warn users when certificates are expired, mismatched, or untrusted."
    ),
    "domain": (
        "Domain registration expires at the registrar. If it lapses, DNS stops working "
        "and the website can disappear even if hosting is fine."
    ),
    "dns": (
        "DNS maps names to servers (A/AAAA) and other records. "
        "Wrong or missing records are a top cause of outages after migrations."
    ),
    "spf": (
        "SPF lists which servers may send email for your domain. Receivers use it to "
        "spot forged senders. Gaps here are important, but mail can still work."
    ),
    "dkim": (
        "DKIM is a digital stamp on outbound mail. Receivers look up "
        "selector._domainkey in DNS. WHM checks common selectors (s1, s2, em, default); "
        "a custom selector can still exist, so always confirm in your email provider. "
        "Tip: many DNS panels auto-add your domain to the host — enter only s1._domainkey, "
        "not the full name, or you may create a doubled hostname that fails verification."
    ),
    "dmarc": (
        "DMARC says what to do when SPF/DKIM fail: p=none only monitors, "
        "quarantine/reject actually protect against spoofing. Tighten policy only after "
        "SPF and DKIM pass on real messages."
    ),
    "mx": (
        "MX records tell the internet where to deliver inbound email for the domain."
    ),
    "smtp": (
        "SMTP ports 25/465/587 are used to accept or submit mail. Port 25 is often blocked "
        "on client networks; treat failures there as informational."
    ),
    "sendgrid": (
        "Only shown when this domain already looks like it uses SendGrid "
        "(SPF include:sendgrid.net or s1/s2 CNAMEs). "
        "Domain Authentication needs those CNAMEs in DNS — enter only the short host "
        "(e.g. s1._domainkey); many panels auto-add the domain and doubling it breaks DKIM."
    ),
    "security": (
        "Security headers are small instructions the website sends to browsers to reduce "
        "common attacks. Missing headers do not always break the site, but they are good practice."
    ),
    "performance": (
        "Speed checks measure how long the website takes to respond. Slow results can mean "
        "hosting problems — or a weak internet connection while testing."
    ),
    "hosting": (
        "Hosting detection is a best guess from public clues (headers and page content). "
        "It helps support teams know where the site likely lives."
    ),
    "technology": (
        "Technology detection guesses tools like WordPress or React from public page clues."
    ),
}


def blurb_for(category: str) -> str:
    return EDUCATION.get(category, "")
