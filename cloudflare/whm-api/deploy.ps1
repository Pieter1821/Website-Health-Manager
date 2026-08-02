# Interactive helper: create D1, migrate schema, set secret, deploy Worker.
# Requires: Node.js, Cloudflare account. Opens browser for `wrangler login` if needed.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "wrangler.toml")) {
    if (-not (Test-Path "wrangler.toml.example")) {
        throw "Missing wrangler.toml.example"
    }
    Copy-Item "wrangler.toml.example" "wrangler.toml"
    Write-Host "Created local wrangler.toml from example (gitignored)."
}

if (-not (Test-Path "node_modules")) {
    npm install
}

Write-Host "Checking Cloudflare login..."
$whoami = npx wrangler whoami 2>&1 | Out-String
if ($whoami -match "not authenticated") {
    Write-Host "Opening browser for wrangler login..."
    npx wrangler login
}

$toml = Get-Content "wrangler.toml" -Raw
if ($toml -match "REPLACE_WITH_D1_DATABASE_ID") {
    Write-Host "Creating D1 database whm-db..."
    $createOut = npx wrangler d1 create whm-db 2>&1 | Out-String
    Write-Host $createOut
    if ($createOut -match 'database_id\s*=\s*"([^"]+)"') {
        $id = $Matches[1]
        $toml = $toml -replace "REPLACE_WITH_D1_DATABASE_ID", $id
        Set-Content -Path "wrangler.toml" -Value $toml -NoNewline
        Write-Host "Wrote database_id=$id into wrangler.toml"
    } else {
        Write-Host "Could not parse database_id from wrangler output."
        Write-Host "Paste it into wrangler.toml manually, then re-run this script."
        exit 1
    }
}

Write-Host "Applying schema to remote D1..."
npm run db:migrate:remote

Write-Host "Set WHM_API_TOKEN (paste a long random secret)..."
npx wrangler secret put WHM_API_TOKEN

Write-Host "Deploying Worker..."
npm run deploy

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1) Copy the workers.dev URL from above"
Write-Host "  2) From repo root, migrate local data:"
Write-Host '     python -m whm.migrate_to_cloud --api-url https://WHM-API.URL --token YOUR_TOKEN --yes --save-config'
Write-Host "  3) Restart Website Health Manager"
Write-Host "Guide: docs/cloudflare-d1.md"
