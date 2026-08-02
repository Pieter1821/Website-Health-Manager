-- Website Health Manager — Cloudflare D1 schema (SQLite-compatible)

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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    totp_last_step INTEGER,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_websites_domain ON websites(domain);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_health_website_checked ON health_checks(website_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_dns_website_captured ON dns_snapshots(website_id, captured_at DESC);
