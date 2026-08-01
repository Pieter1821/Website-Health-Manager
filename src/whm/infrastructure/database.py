"""SQLite schema and connection helpers."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

# sqlite3.Connection in 3.13+ cannot hold custom attrs / weakrefs — key by id.
_CONN_LOCKS: dict[int, threading.RLock] = {}


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS websites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    display_name TEXT NOT NULL,
    customer_id INTEGER,
    dkim_selectors TEXT NOT NULL DEFAULT 's1,s2,em,default',
    check_interval TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    last_checked_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    website_status TEXT NOT NULL,
    ssl_status TEXT NOT NULL,
    domain_status TEXT NOT NULL,
    dns_status TEXT NOT NULL,
    email_status TEXT NOT NULL,
    response_time_ms REAL,
    duration_ms REAL,
    error_message TEXT NOT NULL DEFAULT '',
    findings_json TEXT NOT NULL DEFAULT '[]',
    dns_records_json TEXT NOT NULL DEFAULT '[]',
    raw_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (website_id) REFERENCES websites(id)
);

CREATE TABLE IF NOT EXISTS dns_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_id INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    records_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (website_id) REFERENCES websites(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "timeout_seconds": "10",
    "dns_server": "",
    "theme": "clam",
    "export_folder": "exports",
    "check_interval": "manual",
    "notify_on": "critical",
    "notify_desktop": "1",
    "slack_webhook": "",
    "discord_webhook": "",
    "teams_webhook": "",
    "generic_webhook": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "mail_from": "",
    "mail_to": "",
    "simple_mode": "1",
}


def default_db_path() -> Path:
    """Store the DB under the user's home folder."""
    root = Path.home() / ".whm"
    root.mkdir(parents=True, exist_ok=True)
    return root / "whm.db"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open SQLite with row factory, foreign keys, and a thread lock."""
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # ThreadingHTTPServer + scan workers share one connection — serialize access.
    _CONN_LOCKS[id(conn)] = threading.RLock()
    return conn


def locked(conn: sqlite3.Connection) -> threading.RLock:
    """Return the per-connection lock used to serialize DB access."""
    key = id(conn)
    lock = _CONN_LOCKS.get(key)
    if lock is None:
        lock = threading.RLock()
        _CONN_LOCKS[key] = lock
    return lock


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create tables, migrate older DBs, and seed default settings."""
    conn.executescript(SCHEMA)
    _ensure_column(conn, "websites", "check_interval", "TEXT NOT NULL DEFAULT 'manual'")
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
