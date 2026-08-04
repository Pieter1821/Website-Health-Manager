# Shared cloud database for the desktop app (Cloudflare D1)

Website Health Manager stays a **desktop app**. Cloudflare is only private remote storage: the installed app on each PC calls a locked-down HTTPS API and reads/writes the shared SQLite (D1) database.

**Access model:** email/password sign-in → 30-day session JWT. The desktop client header (`X-WHM-Client: desktop`) is required; random clients get a blank 404. Bootstrap `WHM_API_TOKEN` is for migrate / one-time admin creation only — **never** put it in desktop `cloud.json`.

Local SQLite (`%USERPROFILE%\.whm\whm.db`) remains the default. Cloud mode is opt-in via `%USERPROFILE%\.whm\cloud.json`.

## What you get

- One shared database for every desktop install that points at the same API
- **Authentication:** email or legacy username (e.g. `admin`) + password → session JWT (no MFA)
- SMTP passwords and alert webhooks stay on each PC (never synced to D1)

## What stays on each PC

- Health **scans** still run in the desktop app (from that machine)
- Alert credentials (SMTP / Slack / Teams / Discord / generic webhooks)
- Results are saved to D1 so other PCs see the same list

---

## 1. Prerequisites

- A [Cloudflare](https://dash.cloudflare.com/) account (free plan is enough)
- Node.js 18+ and npm
- Wrangler logged in: `npx wrangler login`

## 2. Create D1 + deploy the API

```powershell
cd cloudflare\whm-api
npm install
Copy-Item wrangler.toml.example wrangler.toml   # local only — gitignored
npm run db:create
```

Paste the printed `database_id` into your **local** `wrangler.toml` (never commit this file).

```powershell
npm run db:migrate:remote
npm run db:migrate:users:remote
npx wrangler secret put WHM_API_TOKEN      # bootstrap / migrate only (keep secret)
npx wrangler secret put WHM_JWT_SECRET     # signs desktop session JWTs (required for login)
npm run deploy
```

## 3. Migrate local data → D1 (one-shot)

Run this on the PC that has the websites you want in the cloud (usually your work laptop):

```powershell
python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token YOUR_BOOTSTRAP_TOKEN --dry-run
python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token YOUR_BOOTSTRAP_TOKEN --yes --save-config --bootstrap-user admin --bootstrap-password "your-long-password"
```

`--save-config` writes **api_url only** to `cloud.json` (never the bootstrap token).  
`--bootstrap-user` creates the first admin when the users table is empty.  
Local DB is left untouched. Secret settings are **not** uploaded.  
**Warning:** migrate **replaces** all cloud site data with this PC’s local DB.

## 4. Point each desktop at the Worker

`%USERPROFILE%\.whm\cloud.json` on **every** PC:

```json
{
  "api_url": "https://whm-api.xxx.workers.dev"
}
```

Open the app → sign in with email/password (or legacy username `admin`). After login, the file gains `session_token` / `session_expires_at` (30-day TTL). Sessions work across PCs — sign in once per machine.

Force local storage: `$env:WHM_STORAGE = "local"`.

### Forgot admin password?

1. If the users table is empty: re-run migrate with `--bootstrap-user` / `--bootstrap-password` (bootstrap token via `--token` or env — not cloud.json).
2. If another admin exists: they can reset the password from **Users** in the desktop app.
3. If you are locked out with an existing `admin` user: use Wrangler D1 to delete that row, then bootstrap again; or hash a new password offline and `UPDATE` the `password_hash` (same PBKDF2 format the Worker uses).

## Project files

| Path | Role |
|------|------|
| `cloudflare/whm-api/` | Private HTTPS API + D1 schema + auth |
| `src/whm/infrastructure/cloud_*.py` | Desktop HTTPS client + repositories |
| `src/whm/infrastructure/hybrid_settings.py` | Local secrets + cloud non-secret settings |
| `src/whm/migrate_to_cloud.py` | Local → D1 export from this PC |
