"""One-shot: seed a private demo DB and capture README screenshot (no real clients)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from whm.infrastructure.database import connect, initialize_database  # noqa: E402
from whm.main import build_services  # noqa: E402
from whm.presentation.webapi import start_server  # noqa: E402

ASSETS = Path(__file__).resolve().parent
DEMO_DB = ASSETS / "_demo_screenshot.db"
OUT_JPG = ASSETS / "screenshot.jpg"


def seed(db: Path) -> None:
    if db.exists():
        db.unlink()
    conn = connect(db)
    initialize_database(conn)
    now = datetime.now(timezone.utc)
    checked = now.isoformat()
    demos = [
        (
            "https://demo-shop.example",
            "demo-shop.example",
            "Demo Shop",
            "critical",
            "high",
            "healthy",
            "healthy",
            "healthy",
            "healthy",
            "critical",
            420.0,
            "2026-10-12",
            72,
            "2027-03-01",
            212,
        ),
        (
            "https://northwind.example",
            "northwind.example",
            "Northwind Mail",
            "warning",
            "medium",
            "healthy",
            "healthy",
            "healthy",
            "healthy",
            "warning",
            880.0,
            "2026-11-20",
            111,
            "2027-08-15",
            379,
        ),
        (
            "https://contoso-agency.example",
            "contoso-agency.example",
            "Contoso Agency",
            "healthy",
            "low",
            "healthy",
            "healthy",
            "healthy",
            "healthy",
            "healthy",
            310.0,
            "2027-01-05",
            157,
            "2028-01-10",
            527,
        ),
    ]
    for (
        url,
        domain,
        name,
        overall,
        risk,
        web,
        ssl,
        dom,
        dns,
        email,
        ms,
        ssl_exp,
        ssl_days,
        dom_exp,
        dom_days,
    ) in demos:
        cur = conn.execute(
            """
            INSERT INTO websites
            (url, domain, display_name, customer_id, dkim_selectors, created_at, last_checked_at, check_interval)
            VALUES (?, ?, ?, NULL, 's1,s2,em,default', ?, ?, 'manual')
            """,
            (url, domain, name, checked, checked),
        )
        wid = int(cur.lastrowid)
        raw = {
            "ssl": {"not_after": ssl_exp, "days_remaining": ssl_days},
            "whois": {"expiration_date": dom_exp, "days_remaining": dom_days},
        }
        conn.execute(
            """
            INSERT INTO health_checks (
                website_id, checked_at, overall_status, risk_level,
                website_status, ssl_status, domain_status, dns_status, email_status,
                response_time_ms, duration_ms, error_message,
                findings_json, dns_records_json, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '[]', '[]', ?)
            """,
            (
                wid,
                checked,
                overall,
                risk,
                web,
                ssl,
                dom,
                dns,
                email,
                ms,
                2500.0,
                json.dumps(raw),
            ),
        )
    conn.commit()
    conn.close()


def main() -> None:
    seed(DEMO_DB)
    websites, scans, settings, conn = build_services(DEMO_DB)
    # Dedicated high port so we never screenshot a live client DB on 17865.
    server, url = start_server(websites, scans, settings, port=27991)
    assert "27991" in url, f"Expected demo port, got {url}"
    try:
        with urllib.request.urlopen(url + "api/sites", timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        names = [s["display_name"] for s in payload.get("sites", [])]
        banned = ("mzansi", "lendo", "presto", "asha", "safenet")
        lowered = " ".join(names).lower()
        if any(b in lowered for b in banned):
            raise SystemExit(f"Refusing to screenshot client names: {names}")
        if not names:
            raise SystemExit("Demo DB has no sites")
        print("Demo sites:", ", ".join(names))

        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        out_png = ASSETS / "_shot.png"
        import subprocess

        subprocess.run(
            [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1400,900",
                f"--screenshot={out_png}",
                url,
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        from PIL import Image

        im = Image.open(out_png).convert("RGB")
        im = im.resize((1200, int(im.height * 1200 / im.width)), Image.Resampling.LANCZOS)
        im.save(OUT_JPG, quality=82, optimize=True, progressive=True)
        out_png.unlink(missing_ok=True)
        print(f"Wrote {OUT_JPG} ({OUT_JPG.stat().st_size} bytes) from {url}")
    finally:
        server.shutdown()
        server.server_close()
        conn.close()
        time.sleep(0.3)
        DEMO_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
