# whm-api (Cloudflare Worker + D1)

Thin authenticated API for Website Health Manager.

Full guide: [`../../docs/cloudflare-d1.md`](../../docs/cloudflare-d1.md)

```powershell
npm install
Copy-Item wrangler.toml.example wrangler.toml   # local only (gitignored)
npm run db:create          # paste database_id into wrangler.toml — never commit it
npm run db:migrate:remote
npx wrangler secret put WHM_API_TOKEN           # secret stays in Cloudflare, not git
npm run deploy
```

`wrangler.toml` holds your real `database_id` and is **gitignored**. Only `wrangler.toml.example` is committed.

The deployed API is **private**: requests without a valid bearer token get a blank 404. Do not share the URL or token publicly.
