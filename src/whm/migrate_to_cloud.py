"""Export local ~/.whm/whm.db and push it to Cloudflare D1 via the Worker API.

Usage:
  python -m whm.migrate_to_cloud
  python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token SECRET

Requires WHM_API_URL + WHM_API_TOKEN (env or ~/.whm/cloud.json), or CLI flags.
This REPLACES all cloud data. Local SQLite is left untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from whm.infrastructure.cloud_client import CloudApiClient, CloudApiError
from whm.infrastructure.cloud_config import CloudConfig, load_cloud_config, save_cloud_config
from whm.infrastructure.database import connect, default_db_path, initialize_database


def dump_local_db(db_path: Path) -> dict[str, Any]:
    conn = connect(db_path)
    initialize_database(conn)
    customers = [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY id")]
    websites = [dict(r) for r in conn.execute("SELECT * FROM websites ORDER BY id")]
    health_checks = [
        dict(r) for r in conn.execute("SELECT * FROM health_checks ORDER BY id")
    ]
    dns_snapshots = [
        dict(r) for r in conn.execute("SELECT * FROM dns_snapshots ORDER BY id")
    ]
    settings_rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {str(r["key"]): str(r["value"]) for r in settings_rows}
    conn.close()
    return {
        "confirm": "replace-cloud-data",
        "customers": customers,
        "websites": websites,
        "health_checks": health_checks,
        "dns_snapshots": dns_snapshots,
        "settings": settings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate local WHM SQLite data to Cloudflare D1 (via Worker API)."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Local SQLite path (default: ~/.whm/whm.db)",
    )
    parser.add_argument("--api-url", default="", help="Worker base URL")
    parser.add_argument("--token", default="", help="WHM_API_TOKEN bearer secret")
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Write api-url/token to ~/.whm/cloud.json after a successful migrate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print dump summary only; do not call the API",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation",
    )
    args = parser.parse_args(argv)

    db_path = args.db or default_db_path()
    if not db_path.exists():
        print(f"Local database not found: {db_path}", file=sys.stderr)
        return 1

    config = load_cloud_config()
    api_url = (args.api_url or (config.api_url if config else "")).strip().rstrip("/")
    token = (args.token or (config.api_token if config else "")).strip()
    if not api_url or not token:
        print(
            "Missing API URL/token. Set WHM_API_URL + WHM_API_TOKEN, "
            "or pass --api-url and --token.",
            file=sys.stderr,
        )
        return 1

    payload = dump_local_db(db_path)
    summary = {
        "customers": len(payload["customers"]),
        "websites": len(payload["websites"]),
        "health_checks": len(payload["health_checks"]),
        "dns_snapshots": len(payload["dns_snapshots"]),
        "settings": len(payload["settings"]),
        "source_db": str(db_path),
        "api_url": api_url,
    }
    print(json.dumps(summary, indent=2))

    if args.dry_run:
        print("Dry run - nothing uploaded.")
        return 0

    if not args.yes:
        answer = input(
            "This REPLACES all data in the cloud D1 database. Continue? [y/N] "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return 1

    client = CloudApiClient(CloudConfig(api_url=api_url, api_token=token), timeout=120.0)
    try:
        result = client.post("/api/migrate", payload)
    except CloudApiError as exc:
        print(f"Migrate failed: {exc}", file=sys.stderr)
        return 1

    print("Migrate OK:", json.dumps(result, indent=2))
    if args.save_config:
        path = save_cloud_config(api_url, token)
        print(f"Saved cloud config to {path}")
    else:
        print(
            "Tip: save connection with --save-config, or set env "
            "WHM_API_URL / WHM_API_TOKEN so the desktop app uses D1."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
