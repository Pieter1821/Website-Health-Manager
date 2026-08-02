/**
 * Private backend for the Website Health Manager *desktop* app (not a website).
 * Desktop clients call this over HTTPS; there is no public web UI here.
 *
 * Access control:
 * - Requires Authorization: Bearer <WHM_API_TOKEN>
 * - Requires X-WHM-Client: desktop (rejects casual browser hits)
 * - Missing/wrong credentials → blank 404
 * - Optional WHM_ALLOWED_IPS: comma-separated client IPs
 */

export default {
  async fetch(request, env) {
    // Browsers send OPTIONS preflight — this is not a web app API.
    if (request.method === "OPTIONS") {
      return notFound();
    }
    try {
      if (!isDesktopClient(request)) {
        return notFound();
      }
      if (!(await authorize(request, env))) {
        return notFound();
      }
      if (!ipAllowed(request, env)) {
        return notFound();
      }
      if (!env.DB) {
        return json({ error: "D1 binding DB is missing — check wrangler.toml" }, 500);
      }
      const url = new URL(request.url);
      const path = url.pathname.replace(/\/+$/, "") || "/";
      return await route(request, env, url, path);
    } catch (err) {
      console.error(err);
      return json({ error: "Internal error" }, 500);
    }
  },
};

function notFound() {
  return new Response(null, { status: 404 });
}

function isDesktopClient(request) {
  const client = (request.headers.get("X-WHM-Client") || "").trim().toLowerCase();
  return client === "desktop";
}

async function authorize(request, env) {
  const expected = (env.WHM_API_TOKEN || "").trim();
  if (!expected) {
    // Fail closed if secret not configured.
    return false;
  }
  const header = request.headers.get("Authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return false;
  return timingSafeEqual(token, expected);
}

function ipAllowed(request, env) {
  const raw = (env.WHM_ALLOWED_IPS || "").trim();
  if (!raw) return true; // unset = token-only gate (default)
  const allowed = new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  );
  if (!allowed.size) return true;
  const ip = request.headers.get("CF-Connecting-IP") || "";
  return allowed.has(ip);
}

/** Constant-time string compare (UTF-8). */
async function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const aa = enc.encode(a);
  const bb = enc.encode(b);
  if (aa.byteLength !== bb.byteLength) {
    // Still hash both lengths' buffers to reduce timing signal on length.
    await crypto.subtle.digest("SHA-256", aa);
    await crypto.subtle.digest("SHA-256", bb);
    return false;
  }
  let out = 0;
  for (let i = 0; i < aa.byteLength; i++) out |= aa[i] ^ bb[i];
  return out === 0;
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

async function route(request, env, url, path) {
  const db = env.DB;
  const method = request.method;

  // Authenticated liveness check (not public).
  if (method === "GET" && path === "/api/health") {
    return json({ ok: true, service: "whm-api" });
  }

  // --- customers ---
  if (method === "GET" && path === "/api/customers") {
    const { results } = await db
      .prepare("SELECT * FROM customers ORDER BY name COLLATE NOCASE")
      .all();
    return json({ customers: results || [] });
  }
  if (method === "POST" && path === "/api/customers") {
    const body = await readJson(request);
    if (!body?.name?.trim()) return json({ error: "name required" }, 400);
    const created_at = body.created_at || new Date().toISOString();
    const r = await db
      .prepare("INSERT INTO customers (name, notes, created_at) VALUES (?, ?, ?)")
      .bind(body.name.trim(), body.notes || "", created_at)
      .run();
    return json({ id: r.meta.last_row_id, name: body.name.trim(), notes: body.notes || "", created_at }, 201);
  }
  let m = path.match(/^\/api\/customers\/(\d+)$/);
  if (method === "GET" && m) {
    const row = await db.prepare("SELECT * FROM customers WHERE id = ?").bind(Number(m[1])).first();
    if (!row) return json({ error: "Not found" }, 404);
    return json(row);
  }
  if (method === "DELETE" && m) {
    const id = Number(m[1]);
    await db.prepare("UPDATE websites SET customer_id = NULL WHERE customer_id = ?").bind(id).run();
    await db.prepare("DELETE FROM customers WHERE id = ?").bind(id).run();
    return json({ ok: true });
  }

  // --- websites ---
  if (method === "GET" && path === "/api/websites") {
    const q = (url.searchParams.get("q") || "").trim();
    if (q) {
      const like = `%${q}%`;
      const { results } = await db
        .prepare(
          `SELECT w.* FROM websites w
           LEFT JOIN customers c ON c.id = w.customer_id
           WHERE w.display_name LIKE ? OR w.domain LIKE ? OR w.url LIKE ?
              OR IFNULL(c.name, '') LIKE ?
           ORDER BY w.display_name COLLATE NOCASE`
        )
        .bind(like, like, like, like)
        .all();
      return json({ websites: results || [] });
    }
    const { results } = await db
      .prepare("SELECT * FROM websites ORDER BY display_name COLLATE NOCASE")
      .all();
    return json({ websites: results || [] });
  }

  if (method === "POST" && path === "/api/websites") {
    const body = await readJson(request);
    if (!body?.url || !body?.domain || !body?.display_name) {
      return json({ error: "url, domain, display_name required" }, 400);
    }
    let customer_id = body.customer_id ?? null;
    if (customer_id != null) {
      const exists = await db.prepare("SELECT 1 FROM customers WHERE id = ?").bind(customer_id).first();
      if (!exists) customer_id = null;
    }
    const created_at = body.created_at || new Date().toISOString();
    const r = await db
      .prepare(
        `INSERT INTO websites
         (url, domain, display_name, customer_id, dkim_selectors, check_interval, created_at, last_checked_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .bind(
        body.url,
        body.domain,
        body.display_name,
        customer_id,
        body.dkim_selectors || "s1,s2,em,default",
        body.check_interval || "manual",
        created_at,
        body.last_checked_at || null
      )
      .run();
    const row = await db.prepare("SELECT * FROM websites WHERE id = ?").bind(r.meta.last_row_id).first();
    return json(row, 201);
  }

  m = path.match(/^\/api\/websites\/(\d+)$/);
  if (m) {
    const id = Number(m[1]);
    if (method === "GET") {
      const row = await db.prepare("SELECT * FROM websites WHERE id = ?").bind(id).first();
      if (!row) return json({ error: "Not found" }, 404);
      return json(row);
    }
    if (method === "PUT") {
      const body = await readJson(request);
      if (!body) return json({ error: "Invalid JSON" }, 400);
      let customer_id = body.customer_id ?? null;
      if (customer_id != null) {
        const exists = await db.prepare("SELECT 1 FROM customers WHERE id = ?").bind(customer_id).first();
        if (!exists) customer_id = null;
      }
      await db
        .prepare(
          `UPDATE websites SET url=?, domain=?, display_name=?, customer_id=?,
           dkim_selectors=?, check_interval=?, last_checked_at=? WHERE id=?`
        )
        .bind(
          body.url,
          body.domain,
          body.display_name,
          customer_id,
          body.dkim_selectors || "s1,s2,em,default",
          body.check_interval || "manual",
          body.last_checked_at || null,
          id
        )
        .run();
      const row = await db.prepare("SELECT * FROM websites WHERE id = ?").bind(id).first();
      return json(row);
    }
    if (method === "DELETE") {
      await db.prepare("DELETE FROM health_checks WHERE website_id = ?").bind(id).run();
      await db.prepare("DELETE FROM dns_snapshots WHERE website_id = ?").bind(id).run();
      await db.prepare("DELETE FROM websites WHERE id = ?").bind(id).run();
      return json({ ok: true });
    }
  }

  // --- health checks ---
  m = path.match(/^\/api\/websites\/(\d+)\/health-checks$/);
  if (m && method === "POST") {
    const website_id = Number(m[1]);
    const exists = await db.prepare("SELECT 1 FROM websites WHERE id = ?").bind(website_id).first();
    if (!exists) return json({ error: "Website not found" }, 404);
    const body = await readJson(request);
    if (!body) return json({ error: "Invalid JSON" }, 400);
    const r = await db
      .prepare(
        `INSERT INTO health_checks (
          website_id, checked_at, overall_status, risk_level,
          website_status, ssl_status, domain_status, dns_status, email_status,
          response_time_ms, duration_ms, error_message,
          findings_json, dns_records_json, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .bind(
        website_id,
        body.checked_at || new Date().toISOString(),
        body.overall_status || "unknown",
        body.risk_level || "unknown",
        body.website_status || "unknown",
        body.ssl_status || "unknown",
        body.domain_status || "unknown",
        body.dns_status || "unknown",
        body.email_status || "healthy",
        body.response_time_ms ?? null,
        body.duration_ms ?? null,
        body.error_message || "",
        typeof body.findings_json === "string" ? body.findings_json : JSON.stringify(body.findings || []),
        typeof body.dns_records_json === "string"
          ? body.dns_records_json
          : JSON.stringify(body.dns_records || []),
        typeof body.raw_json === "string" ? body.raw_json : JSON.stringify(body.raw || {})
      )
      .run();
    const row = await db.prepare("SELECT * FROM health_checks WHERE id = ?").bind(r.meta.last_row_id).first();
    return json(row, 201);
  }

  m = path.match(/^\/api\/websites\/(\d+)\/health-checks\/latest$/);
  if (m && method === "GET") {
    const row = await db
      .prepare(
        `SELECT * FROM health_checks WHERE website_id = ?
         ORDER BY checked_at DESC, id DESC LIMIT 1`
      )
      .bind(Number(m[1]))
      .first();
    return json({ check: row || null });
  }

  m = path.match(/^\/api\/websites\/(\d+)\/health-checks$/);
  if (m && method === "GET") {
    const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") || 20)));
    const { results } = await db
      .prepare(
        `SELECT * FROM health_checks WHERE website_id = ?
         ORDER BY checked_at DESC, id DESC LIMIT ?`
      )
      .bind(Number(m[1]), limit)
      .all();
    return json({ checks: results || [] });
  }

  // --- DNS snapshots ---
  m = path.match(/^\/api\/websites\/(\d+)\/dns-snapshots$/);
  if (m && method === "POST") {
    const website_id = Number(m[1]);
    const exists = await db.prepare("SELECT 1 FROM websites WHERE id = ?").bind(website_id).first();
    if (!exists) return json({ ok: true, skipped: true });
    const body = await readJson(request);
    const r = await db
      .prepare(
        `INSERT INTO dns_snapshots (website_id, captured_at, records_json) VALUES (?, ?, ?)`
      )
      .bind(
        website_id,
        body?.captured_at || new Date().toISOString(),
        typeof body?.records_json === "string"
          ? body.records_json
          : JSON.stringify(body?.records || [])
      )
      .run();
    const row = await db.prepare("SELECT * FROM dns_snapshots WHERE id = ?").bind(r.meta.last_row_id).first();
    return json(row, 201);
  }

  m = path.match(/^\/api\/websites\/(\d+)\/dns-snapshots\/latest$/);
  if (m && method === "GET") {
    const row = await db
      .prepare(
        `SELECT * FROM dns_snapshots WHERE website_id = ?
         ORDER BY captured_at DESC, id DESC LIMIT 1`
      )
      .bind(Number(m[1]))
      .first();
    return json({ snapshot: row || null });
  }

  m = path.match(/^\/api\/websites\/(\d+)\/dns-snapshots\/previous$/);
  if (m && method === "GET") {
    const row = await db
      .prepare(
        `SELECT * FROM dns_snapshots WHERE website_id = ?
         ORDER BY captured_at DESC, id DESC LIMIT 1 OFFSET 1`
      )
      .bind(Number(m[1]))
      .first();
    return json({ snapshot: row || null });
  }

  // --- settings ---
  if (method === "GET" && path === "/api/settings") {
    const { results } = await db.prepare("SELECT key, value FROM settings").all();
    const settings = {};
    for (const row of results || []) settings[row.key] = row.value;
    return json({ settings });
  }
  if (method === "PUT" && path === "/api/settings") {
    const body = await readJson(request);
    const settings = body?.settings || body || {};
    const stmts = [];
    for (const [key, value] of Object.entries(settings)) {
      stmts.push(
        db
          .prepare(
            `INSERT INTO settings (key, value) VALUES (?, ?)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value`
          )
          .bind(String(key), String(value ?? ""))
      );
    }
    if (stmts.length) await db.batch(stmts);
    return json({ ok: true });
  }

  // --- bulk migrate (replace cloud data with a local dump) ---
  if (method === "POST" && path === "/api/migrate") {
    const body = await readJson(request);
    if (!body || body.confirm !== "replace-cloud-data") {
      return json(
        { error: 'Send {"confirm":"replace-cloud-data", "customers":[], ...}' },
        400
      );
    }
    await db.batch([
      db.prepare("DELETE FROM health_checks"),
      db.prepare("DELETE FROM dns_snapshots"),
      db.prepare("DELETE FROM websites"),
      db.prepare("DELETE FROM customers"),
      db.prepare("DELETE FROM settings"),
    ]);

    for (const c of body.customers || []) {
      await db
        .prepare(
          `INSERT INTO customers (id, name, notes, created_at) VALUES (?, ?, ?, ?)`
        )
        .bind(c.id, c.name, c.notes || "", c.created_at)
        .run();
    }
    for (const w of body.websites || []) {
      await db
        .prepare(
          `INSERT INTO websites
           (id, url, domain, display_name, customer_id, dkim_selectors, check_interval, created_at, last_checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .bind(
          w.id,
          w.url,
          w.domain,
          w.display_name,
          w.customer_id ?? null,
          w.dkim_selectors || "s1,s2,em,default",
          w.check_interval || "manual",
          w.created_at,
          w.last_checked_at || null
        )
        .run();
    }
    for (const h of body.health_checks || []) {
      await db
        .prepare(
          `INSERT INTO health_checks (
            id, website_id, checked_at, overall_status, risk_level,
            website_status, ssl_status, domain_status, dns_status, email_status,
            response_time_ms, duration_ms, error_message,
            findings_json, dns_records_json, raw_json
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .bind(
          h.id,
          h.website_id,
          h.checked_at,
          h.overall_status,
          h.risk_level,
          h.website_status,
          h.ssl_status,
          h.domain_status,
          h.dns_status,
          h.email_status || "healthy",
          h.response_time_ms ?? null,
          h.duration_ms ?? null,
          h.error_message || "",
          h.findings_json || "[]",
          h.dns_records_json || "[]",
          h.raw_json || "{}"
        )
        .run();
    }
    for (const d of body.dns_snapshots || []) {
      await db
        .prepare(
          `INSERT INTO dns_snapshots (id, website_id, captured_at, records_json) VALUES (?, ?, ?, ?)`
        )
        .bind(d.id, d.website_id, d.captured_at, d.records_json || "[]")
        .run();
    }
    for (const [key, value] of Object.entries(body.settings || {})) {
      await db
        .prepare(`INSERT INTO settings (key, value) VALUES (?, ?)`)
        .bind(key, String(value ?? ""))
        .run();
    }

    // Keep AUTOINCREMENT sequences past imported ids.
    await db
      .prepare(
        `INSERT INTO sqlite_sequence(name, seq) VALUES ('customers', (SELECT IFNULL(MAX(id),0) FROM customers))
         ON CONFLICT(name) DO UPDATE SET seq = excluded.seq`
      )
      .run()
      .catch(() => {});
    await db
      .prepare(
        `INSERT INTO sqlite_sequence(name, seq) VALUES ('websites', (SELECT IFNULL(MAX(id),0) FROM websites))
         ON CONFLICT(name) DO UPDATE SET seq = excluded.seq`
      )
      .run()
      .catch(() => {});
    await db
      .prepare(
        `INSERT INTO sqlite_sequence(name, seq) VALUES ('health_checks', (SELECT IFNULL(MAX(id),0) FROM health_checks))
         ON CONFLICT(name) DO UPDATE SET seq = excluded.seq`
      )
      .run()
      .catch(() => {});
    await db
      .prepare(
        `INSERT INTO sqlite_sequence(name, seq) VALUES ('dns_snapshots', (SELECT IFNULL(MAX(id),0) FROM dns_snapshots))
         ON CONFLICT(name) DO UPDATE SET seq = excluded.seq`
      )
      .run()
      .catch(() => {});

    return json({
      ok: true,
      imported: {
        customers: (body.customers || []).length,
        websites: (body.websites || []).length,
        health_checks: (body.health_checks || []).length,
        dns_snapshots: (body.dns_snapshots || []).length,
        settings: Object.keys(body.settings || {}).length,
      },
    });
  }

  return json({ error: "Not found", path }, 404);
}
