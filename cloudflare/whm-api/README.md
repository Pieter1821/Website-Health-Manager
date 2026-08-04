# whm-api (Cloudflare Worker + D1)

Thin authenticated API for Website Health Manager.

Full guide: [`../../docs/cloudflare-d1.md`](../../docs/cloudflare-d1.md)

```powershell
npm install
Copy-Item wrangler.toml.example wrangler.toml   # local only (gitignored)
npm run db:create          # paste database_id into wrangler.toml — never commit it
npm run db:migrate:remote
npx wrangler secret put WHM_API_TOKEN           # bootstrap / migrate only
npx wrangler secret put WHM_JWT_SECRET          # required for email/password sessions
npm run deploy
```

`wrangler.toml` holds your real `database_id` and is **gitignored**. Only `wrangler.toml.example` is committed.

The deployed API is **private**:

- Requests without `X-WHM-Client: desktop` get a blank 404
- Data routes require a valid **session JWT** (from `POST /api/auth/login`) or the bootstrap `WHM_API_TOKEN` (migrate / scripts only)
- Desktop apps use `cloud.json` with `api_url` only, then sign in with email/password — do **not** put `WHM_API_TOKEN` in desktop config
