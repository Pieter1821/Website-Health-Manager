# Learning log — Website Health Manager

Concepts introduced while building Phase 1 (app-first).

## Milestone 0 — Scaffold

- **Virtual environment (`.venv`)**: isolated Python packages per project
- **Package vs module**: `whm/` package, `main.py` module
- **`python -m whm`**: runs `__main__.py` inside a package
- **`if __name__ == "__main__"`**: only run when executed directly
- **Imports**: absolute imports like `from whm.main import main`
- **Clean Architecture layers**: presentation → application → domain ← infrastructure

## Milestone 1 — Domain + SQLite

- **`@dataclass`**: concise classes for data
- **`Enum`**: fixed sets of named values (`HealthStatus`)
- **Type hints**: `Optional[int]`, `list[Finding]`
- **ABC / ports**: interfaces (`CustomerRepository`) without implementation
- **SQLite**: tables, `AUTOINCREMENT`, foreign keys, parameterized queries
- **Context of JSON in SQLite**: serialize nested findings as text

## Milestone 2 — HTTP checks

- **`httpx`**: modern HTTP client
- **Exceptions**: catch timeouts / connection errors without crashing
- **`threading`**: run scans off the UI thread
- **`tk.after`**: marshal results back to the main thread safely

## Milestone 3 — SSL

- **Sockets + `ssl`**: open TLS connection, read peer certificate
- **`cryptography` X.509**: parse issuer, SAN, dates
- **Timezone-aware `datetime`**: expiry math in UTC

## Milestone 4 — WHOIS

- **Third-party libraries**: `python-whois`
- **Defensive parsing**: WHOIS fields may be `None`, lists, or naive datetimes
- **Graceful degradation**: `UNKNOWN` when the registry blocks queries

## Milestone 5 — DNS

- **`dnspython`**: resolve A/AAAA/MX/TXT/…
- **Snapshots**: store historical records for comparison
- **Diffing**: set comparison of record tuples

## Milestone 6 — Email / SendGrid

- **SPF / DKIM / DMARC**: DNS TXT policies for mail authenticity
- **Regex lightly**: extract `p=`, `rua=`, `include:`
- **Findings model**: Correct / Incorrect / Missing + recommendations
- **SMTP probe**: TCP connect only (no mail send)

## Milestone 7 — Dashboard UI

- **Tkinter / `ttk`**: frames, buttons, `Treeview`, `Notebook`
- **MVC-ish separation**: UI calls services; services call infrastructure
- **Event binding**: `<<TreeviewSelect>>`, button `command=`

## Milestone 8 — History + change detection

- **Time-series storage**: every scan is a row
- **Old vs new highlighting**: DNS added/removed lines

## Milestone 9 — Polish

- **`logging`**: file + stderr handlers
- **Settings key/value store**
- **`pytest`**: unit tests without network where possible
- **Packaging metadata**: `pyproject.toml`, console script entry point

## Later phases

- **Scheduler thread**: background loops with `threading.Event`
- **Notifications**: PowerShell toast, webhook HTTP POSTs, SMTP email
- **Reports**: CSV/JSON/HTML generation with the standard library
- **Fingerprinting**: regex clues in headers/HTML
- **UX copy**: separate presentation strings from domain enums
- **CI + PyInstaller**: GitHub Actions and a `.spec` file for Windows exe builds
