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
        "and the website/email disappear even if hosting is fine."
    ),
    "dns": (
        "DNS maps names to servers (A/AAAA), mail hosts (MX), and text policies (TXT). "
        "Wrong or missing records are a top cause of outages after migrations."
    ),
    "spf": (
        "SPF (Sender Policy Framework) lists which servers may send email for your domain. "
        "Without it, messages often land in spam or are rejected."
    ),
    "dkim": (
        "DKIM adds a cryptographic signature to outbound mail. Receivers verify the public "
        "key in DNS (selector._domainkey.domain)."
    ),
    "dmarc": (
        "DMARC tells receivers what to do when SPF/DKIM fail (none / quarantine / reject) "
        "and where to send aggregate reports (rua)."
    ),
    "mx": (
        "MX records tell the internet where to deliver inbound email for the domain."
    ),
    "smtp": (
        "SMTP ports 25/465/587 are used to accept or submit mail. Port 25 is often blocked "
        "on client networks; treat failures there as informational."
    ),
    "sendgrid": (
        "SendGrid needs special DNS records so email is trusted. Wrong or missing "
        "SendGrid settings are a very common reason customer email ends up in spam or fails."
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
