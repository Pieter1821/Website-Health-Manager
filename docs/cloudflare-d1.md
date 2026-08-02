# Shared cloud database for the desktop app (Cloudflare D1)

Website Health Manager stays a **desktop app**. Cloudflare is only private remote storage: the installed app on each PC calls a locked-down HTTPS API and reads/writes the shared SQLite (D1) database.

This is **not** a web app, login portal, or public site.

Local SQLite (`%USERPROFILE%\.whm\whm.db`) remains the default. Cloud mode is opt-in via `%USERPROFILE%\.whm\cloud.json`.

## What you get

- One shared database for every desktop install that uses the same API URL + token
- Same schema as local SQLite
- Private API: bearer token + `X-WHM-Client: desktop`. Anything else gets a blank **404**

## What stays on each PC

- Health **scans** still run in the desktop app (from that machine)
- Results are saved to D1 so colleagues see the same history in their desktop app

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

Paste the printed `database_id` into your **local** `wrangler.toml` (never commit this file):

```toml
database_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

The API token is stored only via `wrangler secret put` and in each user's `%USERPROFILE%\.whm\cloud.json` — not in the repo or installer.

```powershell
npm run db:migrate:remote
npx wrangler secret put WHM_API_TOKEN
npm run deploy
```

Note the API URL from deploy output (used only by the desktop app).

Smoke test with the desktop headers (without them you get **404**):

```powershell
curl -H "Authorization: Bearer YOUR_TOKEN" -H "X-WHM-Client: desktop" https://whm-api.xxx.workers.dev/api/health
```

Optional: secret `WHM_ALLOWED_IPS` = comma-separated client IPs. Leave unset for token-only access.

## 3. Migrate local data → D1 (one-shot)

```powershell
python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token YOUR_TOKEN --dry-run
python -m whm.migrate_to_cloud --api-url https://whm-api.xxx.workers.dev --token YOUR_TOKEN --yes --save-config
```

Local DB is left untouched. `--save-config` writes `%USERPROFILE%\.whm\cloud.json`.

## 4. Point the desktop app at the cloud

`%USERPROFILE%\.whm\cloud.json`:

```json
{
  "api_url": "https://whm-api.xxx.workers.dev",
  "api_token": "YOUR_TOKEN"
}
```

Or env vars `WHM_API_URL` / `WHM_API_TOKEN`. Force local storage: `$env:WHM_STORAGE = "local"`.

Share URL + token only with people who should use the shared DB (treat the token like a password).

## Project files

| Path | Role |
|------|------|
| `cloudflare/whm-api/` | Private HTTPS API + D1 schema |
| `src/whm/infrastructure/cloud_*.py` | Desktop HTTPS client + repositories |
| `src/whm/migrate_to_cloud.py` | Local → D1 export from this PC |
