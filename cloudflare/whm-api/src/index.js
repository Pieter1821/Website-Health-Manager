/**
 * Private backend for the Website Health Manager *desktop* app (not a website).
 *
 * Access control:
 * - Requires X-WHM-Client: desktop
 * - Auth routes: login / bootstrap / MFA (no session yet)
 * - Data routes: Bearer JWT session OR legacy WHM_API_TOKEN (admin bootstrap)
 * - Roles: admin | operator | viewer
 * - Missing/wrong credentials → blank 404
 * - Authenticated but forbidden → 403 JSON
 */

import {
  SECRET_SETTING_KEYS,
  clearRateLimit,
  ensureUsersTable,
  forbidden,
  escapeLike,
  generateTotpSecret,
  hashPassword,
  issueMfaTempJwt,
  issueSessionJwt,
  json,
  normalizeUsername,
  notFound,
  otpauthUri,
  publicUser,
  rateLimited,
  resolveAuth,
  roleAllowed,
  unauthorized,
  verifyJwt,
  verifyPassword,
  verifyTotp,
} from "./auth.js";

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return notFound();
    }
    try {
      if (!isDesktopClient(request)) {
        return notFound();
      }
      if (!ipAllowed(request, env)) {
        return notFound();
      }
      if (!env.DB) {
        return json({ error: "D1 binding DB is missing — check wrangler.toml" }, 500);
      }
      await ensureUsersTable(env.DB);
      const url = new URL(request.url);
      const path = url.pathname.replace(/\/+$/, "") || "/";

      if (isPublicAuthPath(methodPath(request.method, path))) {
        return await routeAuth(request, env, path);
      }

      const auth = await resolveAuth(request, env);
      if (!auth) {
        return notFound();
      }
      return await route(request, env, url, path, auth);
    } catch (err) {
      console.error(err);
      return json({ error: "Internal error" }, 500);
    }
  },
};

function methodPath(method, path) {
  return `${method} ${path}`;
}

function isPublicAuthPath(key) {
  return (
    key === "POST /api/auth/bootstrap" ||
    key === "POST /api/auth/login" ||
    key === "POST /api/auth/login/totp" ||
    key === "POST /api/auth/mfa/enroll"
  );
}

function isDesktopClient(request) {
  const client = (request.headers.get("X-WHM-Client") || "").trim().toLowerCase();
  return client === "desktop";
}

function ipAllowed(request, env) {
  const raw = (env.WHM_ALLOWED_IPS || "").trim();
  if (!raw) return true;
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

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function requireRole(auth, roles) {
  if (!roleAllowed(auth, roles)) {
    return forbidden("You do not have permission for this action");
  }
  return null;
}

function clientIp(request) {
  return request.headers.get("CF-Connecting-IP") || "unknown";
}

async function routeAuth(request, env, path) {
  const db = env.DB;
  const jwtSecret = (env.WHM_JWT_SECRET || "").trim();
  const bootstrapToken = (env.WHM_API_TOKEN || "").trim();
  const method = request.method;

  if (method === "POST" && path === "/api/auth/bootstrap") {
    try {
      if (!bootstrapToken) return json({ error: "WHM_API_TOKEN not configured" }, 500);
      const header = request.headers.get("Authorization") || "";
      const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
      if (!token || token !== bootstrapToken) return notFound();

      const countRow = await db.prepare("SELECT COUNT(*) AS n FROM users").first();
      if (Number(countRow?.n || 0) > 0) {
        return json({ error: "Already bootstrapped" }, 409);
      }
      const body = await readJson(request);
      const username = normalizeUsername(body?.username);
      const password = String(body?.password || "");
      if (!username) {
        return json(
          { error: "Username must be 2–64 characters: letters, numbers, . _ -" },
          400
        );
      }
      if (password.length < 10 || password.length > 200) {
        return json({ error: "password must be 10–200 characters" }, 400);
      }

      const now = new Date().toISOString();
      const password_hash = await hashPassword(password);
      const r = await db
        .prepare(
          `INSERT INTO users
           (username, password_hash, role, totp_secret, totp_enabled, disabled, created_at, updated_at)
           VALUES (?, ?, 'admin', NULL, 0, 0, ?, ?)`
        )
        .bind(username, password_hash, now, now)
        .run();
      const newId = r?.meta?.last_row_id ?? null;
      return json(
        {
          ok: true,
          user: {
            id: newId,
            username,
            role: "admin",
            totp_enabled: false,
          },
        },
        201
      );
    } catch (err) {
      console.error(err);
      return json({ error: "Bootstrap failed" }, 500);
    }
  }

  if (!jwtSecret) {
    return json({ error: "WHM_JWT_SECRET not configured" }, 500);
  }

  if (method === "POST" && path === "/api/auth/login") {
    const body = await readJson(request);
    const username = normalizeUsername(body?.username);
    const password = String(body?.password || "");
    if (!username || password.length < 1 || password.length > 200) {
      return unauthorized("Invalid username or password");
    }
    const rlKey = `login:${clientIp(request)}:${username}`;
    if (rateLimited(rlKey)) {
      return json({ error: "Too many attempts — try again later" }, 429);
    }
    // Parameterized query — username is never concatenated into SQL.
    const user = await db
      .prepare("SELECT * FROM users WHERE username = ? COLLATE NOCASE")
      .bind(username)
      .first();
    if (!user || user.disabled || !(await verifyPassword(password, user.password_hash))) {
      return unauthorized("Invalid username or password");
    }
    clearRateLimit(rlKey);

    if (!user.totp_enabled || !user.totp_secret) {
      const secret = generateTotpSecret();
      const now = new Date().toISOString();
      await db
        .prepare(
          `UPDATE users SET totp_secret = ?, totp_enabled = 0, totp_last_step = NULL, updated_at = ?
           WHERE id = ?`
        )
        .bind(secret, now, user.id)
        .run();
      const temp_token = await issueMfaTempJwt(user, jwtSecret, "mfa_enroll");
      return json({
        status: "mfa_enrollment_required",
        temp_token,
        totp_secret: secret,
        otpauth_uri: otpauthUri(user.username, secret),
        user: publicUser({ ...user, totp_enabled: 0 }),
      });
    }

    const temp_token = await issueMfaTempJwt(user, jwtSecret, "mfa_login");
    return json({
      status: "mfa_required",
      temp_token,
      user: publicUser(user),
    });
  }

  if (method === "POST" && path === "/api/auth/login/totp") {
    const body = await readJson(request);
    const temp = String(body?.temp_token || "");
    const code = String(body?.code || "");
    const payload = await verifyJwt(temp, jwtSecret);
    if (!payload || payload.typ !== "mfa_login") {
      return unauthorized("MFA session expired — sign in again");
    }
    const rlKey = `totp:${clientIp(request)}:${payload.username}`;
    if (rateLimited(rlKey)) {
      return json({ error: "Too many attempts — try again later" }, 429);
    }
    const user = await db.prepare("SELECT * FROM users WHERE id = ?").bind(payload.sub).first();
    if (!user || user.disabled || !user.totp_enabled || !user.totp_secret) {
      return unauthorized("Invalid MFA session");
    }
    const result = await verifyTotp(user.totp_secret, code, {
      lastStep: user.totp_last_step,
    });
    if (!result.ok) {
      return unauthorized("Invalid authenticator code");
    }
    clearRateLimit(rlKey);
    const now = new Date().toISOString();
    await db
      .prepare("UPDATE users SET totp_last_step = ?, updated_at = ? WHERE id = ?")
      .bind(result.step, now, user.id)
      .run();
    const token = await issueSessionJwt(user, jwtSecret);
    return json({
      status: "ok",
      token,
      expires_in: 12 * 60 * 60,
      user: publicUser(user),
    });
  }

  if (method === "POST" && path === "/api/auth/mfa/enroll") {
    const body = await readJson(request);
    const temp = String(body?.temp_token || "");
    const code = String(body?.code || "");
    const payload = await verifyJwt(temp, jwtSecret);
    if (!payload || payload.typ !== "mfa_enroll") {
      return unauthorized("Enrollment session expired — sign in again");
    }
    const user = await db.prepare("SELECT * FROM users WHERE id = ?").bind(payload.sub).first();
    if (!user || user.disabled || !user.totp_secret) {
      return unauthorized("Invalid enrollment session");
    }
    const result = await verifyTotp(user.totp_secret, code, { lastStep: null });
    if (!result.ok) {
      return unauthorized("Invalid authenticator code");
    }
    const now = new Date().toISOString();
    await db
      .prepare(
        `UPDATE users SET totp_enabled = 1, totp_last_step = ?, updated_at = ? WHERE id = ?`
      )
      .bind(result.step, now, user.id)
      .run();
    const token = await issueSessionJwt(user, jwtSecret);
    return json({
      status: "ok",
      token,
      expires_in: 12 * 60 * 60,
      user: publicUser({ ...user, totp_enabled: 1 }),
    });
  }

  return notFound();
}

async function route(request, env, url, path, auth) {
  const db = env.DB;
  const method = request.method;

  if (method === "GET" && path === "/api/health") {
    return json({ ok: true, service: "whm-api", auth: { role: auth.role, username: auth.username } });
  }

  if (method === "GET" && path === "/api/auth/me") {
    if (auth.type === "bootstrap") {
      return json({ user: { username: "bootstrap", role: "admin", totp_enabled: false } });
    }
    const user = await db.prepare("SELECT * FROM users WHERE id = ?").bind(auth.userId).first();
    if (!user || user.disabled) return unauthorized("Session invalid");
    return json({ user: publicUser(user) });
  }

  // --- users (admin) ---
  if (method === "GET" && path === "/api/users") {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
    const { results } = await db
      .prepare("SELECT * FROM users ORDER BY username COLLATE NOCASE")
      .all();
    return json({ users: (results || []).map(publicUser) });
  }

  if (method === "POST" && path === "/api/users") {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
    const body = await readJson(request);
    const username = normalizeUsername(body?.username);
    const password = String(body?.password || "");
    const role = String(body?.role || "operator");
    if (!username) {
      return json(
        { error: "Username must be 2–64 characters: letters, numbers, . _ -" },
        400
      );
    }
    if (password.length < 10 || password.length > 200) {
      return json({ error: "password must be 10–200 characters" }, 400);
    }
    if (!["admin", "operator", "viewer"].includes(role)) {
      return json({ error: "invalid role" }, 400);
    }
    const now = new Date().toISOString();
    try {
      const r = await db
        .prepare(
          `INSERT INTO users
           (username, password_hash, role, totp_secret, totp_enabled, disabled, created_at, updated_at)
           VALUES (?, ?, ?, NULL, 0, 0, ?, ?)`
        )
        .bind(username, await hashPassword(password), role, now, now)
        .run();
      const row = await db.prepare("SELECT * FROM users WHERE id = ?").bind(r.meta.last_row_id).first();
      return json({ user: publicUser(row) }, 201);
    } catch {
      return json({ error: "Username already exists" }, 409);
    }
  }

  let m = path.match(/^\/api\/users\/(\d+)$/);
  if (m) {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
    const id = Number(m[1]);
    if (method === "PATCH") {
      const body = await readJson(request);
      const user = await db.prepare("SELECT * FROM users WHERE id = ?").bind(id).first();
      if (!user) return json({ error: "Not found" }, 404);
      const role = body?.role != null ? String(body.role) : user.role;
      if (!["admin", "operator", "viewer"].includes(role)) {
        return json({ error: "invalid role" }, 400);
      }
      const disabled =
        body?.disabled != null ? (body.disabled ? 1 : 0) : user.disabled ? 1 : 0;
      let password_hash = user.password_hash;
      if (body?.password) {
        if (String(body.password).length < 10) {
          return json({ error: "password must be at least 10 characters" }, 400);
        }
        password_hash = await hashPassword(String(body.password));
      }
      const now = new Date().toISOString();
      await db
        .prepare(
          `UPDATE users SET role = ?, disabled = ?, password_hash = ?, updated_at = ? WHERE id = ?`
        )
        .bind(role, disabled, password_hash, now, id)
        .run();
      const row = await db.prepare("SELECT * FROM users WHERE id = ?").bind(id).first();
      return json({ user: publicUser(row) });
    }
    if (method === "DELETE") {
      if (auth.userId != null && Number(auth.userId) === id) {
        return json({ error: "Cannot delete your own account" }, 400);
      }
      await db.prepare("DELETE FROM users WHERE id = ?").bind(id).run();
      return json({ ok: true });
    }
  }

  m = path.match(/^\/api\/users\/(\d+)\/reset-mfa$/);
  if (m && method === "POST") {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
    const id = Number(m[1]);
    const now = new Date().toISOString();
    await db
      .prepare(
        `UPDATE users SET totp_secret = NULL, totp_enabled = 0, totp_last_step = NULL, updated_at = ?
         WHERE id = ?`
      )
      .bind(now, id)
      .run();
    return json({ ok: true });
  }

  // --- customers ---
  if (method === "GET" && path === "/api/customers") {
    const { results } = await db
      .prepare("SELECT * FROM customers ORDER BY name COLLATE NOCASE")
      .all();
    return json({ customers: results || [] });
  }
  if (method === "POST" && path === "/api/customers") {
    const denied = requireRole(auth, ["admin", "operator"]);
    if (denied) return denied;
    const body = await readJson(request);
    if (!body?.name?.trim()) return json({ error: "name required" }, 400);
    const created_at = body.created_at || new Date().toISOString();
    const r = await db
      .prepare("INSERT INTO customers (name, notes, created_at) VALUES (?, ?, ?)")
      .bind(body.name.trim(), body.notes || "", created_at)
      .run();
    return json(
      { id: r.meta.last_row_id, name: body.name.trim(), notes: body.notes || "", created_at },
      201
    );
  }
  m = path.match(/^\/api\/customers\/(\d+)$/);
  if (method === "GET" && m) {
    const row = await db.prepare("SELECT * FROM customers WHERE id = ?").bind(Number(m[1])).first();
    if (!row) return json({ error: "Not found" }, 404);
    return json(row);
  }
  if (method === "DELETE" && m) {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
    const id = Number(m[1]);
    await db.prepare("UPDATE websites SET customer_id = NULL WHERE customer_id = ?").bind(id).run();
    await db.prepare("DELETE FROM customers WHERE id = ?").bind(id).run();
    return json({ ok: true });
  }

  // --- websites ---
  if (method === "GET" && path === "/api/websites") {
    const q = (url.searchParams.get("q") || "").trim();
    if (q) {
      // Bound parameters + escaped LIKE wildcards (not string-built SQL).
      const like = `%${escapeLike(q)}%`;
      const { results } = await db
        .prepare(
          `SELECT w.* FROM websites w
           LEFT JOIN customers c ON c.id = w.customer_id
           WHERE w.display_name LIKE ? ESCAPE '\\'
              OR w.domain LIKE ? ESCAPE '\\'
              OR w.url LIKE ? ESCAPE '\\'
              OR IFNULL(c.name, '') LIKE ? ESCAPE '\\'
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
    const denied = requireRole(auth, ["admin", "operator"]);
    if (denied) return denied;
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
      const denied = requireRole(auth, ["admin", "operator"]);
      if (denied) return denied;
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
      const denied = requireRole(auth, ["admin"]);
      if (denied) return denied;
      await db.prepare("DELETE FROM health_checks WHERE website_id = ?").bind(id).run();
      await db.prepare("DELETE FROM dns_snapshots WHERE website_id = ?").bind(id).run();
      await db.prepare("DELETE FROM websites WHERE id = ?").bind(id).run();
      return json({ ok: true });
    }
  }

  // --- health checks ---
  m = path.match(/^\/api\/websites\/(\d+)\/health-checks$/);
  if (m && method === "POST") {
    const denied = requireRole(auth, ["admin", "operator"]);
    if (denied) return denied;
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
    const denied = requireRole(auth, ["admin", "operator"]);
    if (denied) return denied;
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
    for (const row of results || []) {
      if (SECRET_SETTING_KEYS.has(row.key)) continue;
      settings[row.key] = row.value;
    }
    return json({ settings });
  }
  if (method === "PUT" && path === "/api/settings") {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
    const body = await readJson(request);
    const settings = body?.settings || body || {};
    const stmts = [];
    const rejected = [];
    for (const [key, value] of Object.entries(settings)) {
      if (SECRET_SETTING_KEYS.has(String(key))) {
        rejected.push(String(key));
        continue;
      }
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
    return json({ ok: true, rejected_secret_keys: rejected });
  }

  // --- bulk migrate (admin / bootstrap only) ---
  if (method === "POST" && path === "/api/migrate") {
    const denied = requireRole(auth, ["admin"]);
    if (denied) return denied;
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
      if (SECRET_SETTING_KEYS.has(String(key))) continue;
      await db
        .prepare(`INSERT INTO settings (key, value) VALUES (?, ?)`)
        .bind(key, String(value ?? ""))
        .run();
    }

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
        settings: Object.keys(body.settings || {}).filter((k) => !SECRET_SETTING_KEYS.has(k))
          .length,
      },
    });
  }

  return json({ error: "Not found", path }, 404);
}
