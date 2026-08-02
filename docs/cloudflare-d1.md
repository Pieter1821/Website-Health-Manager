# Shared cloud database for the desktop app (Cloudflare D1)

Website Health Manager stays a **desktop app**. Cloudflare is only private remote storage: the installed app on each PC calls a locked-down HTTPS API and reads/writes the shared SQLite (D1) database.

This is **not** a public website. Access requires the desktop client header plus a signed-in user (username / password / TOTP) or the bootstrap API token for setup scripts.

Local SQLite (`%USERPROFILE%\.whm\whm.db`) remains the default. Cloud mode is opt-in via `%USERPROFILE%\.whm\cloud.json`.

## What you get

- One shared database for every desktop install that points at the same API
- **Authentication:** username + password + authenticator (TOTP / Google Authenticator)
- **Authorization:** roles `admin` / `operator` / `viewer`
- SMTP passwords and alert webhooks stay on each PC (never synced to D1)

## What stays on each PC

- Health **scans** still run in the desktop app (from that machine)
- Alert credentials (SMTP / Slack / Teams / Discord / generic webhooks)
- Results are saved to D1 so colleagues see the same history after they sign in

## Roles

| Role | Can do |
|------|--------|
| `viewer` | Read sites, checks, export |
| `operator` | Also add/check/import sites |
| `admin` | Also delete, clear-all, cloud settings, manage users / reset MFA |

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
npx wrangler secret put WHM_API_TOKEN      # bootstrap / migrate only
npx wrangler secret put WHM_JWT_SECRET     # required for login sessions
npm run deploy
```

Note the API URL from deploy output.

Optional: secret `WHM_ALLOWED_IPS` = comma-separated client IPs.

Smoke test (bootstrap token still works as admin for scripts):

```powershell
curl -H "Authorization: Bearer YOUR_BOOTSTRAP_TOKEN" -H "X-WHM-Client: desktop" https://whm-api.xxx.workers.dev/api/health
```

## 3. Migrate local data → D1 (one-shot)

```powershell
python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token YOUR_BOOTSTRAP_TOKEN --dry-run
python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token YOUR_BOOTSTRAP_TOKEN --yes --save-config --bootstrap-user admin --bootstrap-password "a-long-password"
```

Local DB is left untouched. Secret settings are **not** uploaded. `--bootstrap-user` creates the first admin when the users table is empty.

## 4. Sign in from the desktop app

`%USERPROFILE%\.whm\cloud.json` only needs the API URL (session JWT is written after login):

```json
{
  "api_url": "https://whm-api.xxx.workers.dev"
}
```

1. Open Website Health Manager.
2. Sign in with username + password.
3. On first login, scan the QR with an authenticator app and confirm the 6-digit code ([TOTP / PyOTP-compatible](https://pyauth.github.io/pyotp/)).
4. Admins can open **Users** to create operators/viewers or reset MFA.

Force local storage: `$env:WHM_STORAGE = "local"`.

## Recovery

- Lost authenticator: an **admin** uses **Users → Reset MFA** for that account; next login re-enrolls.
- Lost admin access: use `WHM_API_TOKEN` with `POST /api/auth/bootstrap` only if the users table is empty, or reset MFA / create users via a remaining admin session.

## Project files

| Path | Role |
|------|------|
| `cloudflare/whm-api/` | Private HTTPS API + D1 schema + auth |
| `src/whm/infrastructure/cloud_*.py` | Desktop HTTPS client + repositories |
| `src/whm/infrastructure/hybrid_settings.py` | Local secrets + cloud non-secret settings |
| `src/whm/migrate_to_cloud.py` | Local → D1 export from this PC |
