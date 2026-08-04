/**
 * Email/password + JWT session helpers for WHM Worker.
 */

const PBKDF2_ITERATIONS = 100000;
const SESSION_TTL_SEC = 30 * 24 * 60 * 60; // 30 days
const MAX_FAILS = 8;
const FAIL_WINDOW_MS = 15 * 60 * 1000;

/** @type {Map<string, {count:number, resetAt:number}>} */
const failBuckets = new Map();

export const SECRET_SETTING_KEYS = new Set([
  "smtp_password",
  "smtp_username",
  "smtp_host",
  "mail_from",
  "mail_to",
  "slack_webhook",
  "discord_webhook",
  "teams_webhook",
  "generic_webhook",
]);

export const SESSION_TTL_SECONDS = SESSION_TTL_SEC;

export function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export function notFound() {
  return new Response(null, { status: 404 });
}

export function forbidden(message = "Forbidden") {
  return json({ error: message }, 403);
}

export function unauthorized(message = "Unauthorized") {
  return json({ error: message }, 401);
}

export async function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const aa = enc.encode(a);
  const bb = enc.encode(b);
  if (aa.byteLength !== bb.byteLength) {
    await crypto.subtle.digest("SHA-256", aa);
    await crypto.subtle.digest("SHA-256", bb);
    return false;
  }
  let out = 0;
  for (let i = 0; i < aa.byteLength; i++) out |= aa[i] ^ bb[i];
  return out === 0;
}

function b64url(bytes) {
  let bin = "";
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function b64urlJson(obj) {
  return b64url(new TextEncoder().encode(JSON.stringify(obj)));
}

async function hmacKey(secret) {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

export async function signJwt(payload, secret) {
  const header = b64urlJson({ alg: "HS256", typ: "JWT" });
  const body = b64urlJson(payload);
  const data = `${header}.${body}`;
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return `${data}.${b64url(sig)}`;
}

export async function verifyJwt(token, secret) {
  if (!token || !secret) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [header, body, sig] = parts;
  const data = `${header}.${body}`;
  const key = await hmacKey(secret);
  const expected = b64url(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data))
  );
  if (!(await timingSafeEqual(sig, expected))) return null;
  try {
    const jsonStr = atob(body.replace(/-/g, "+").replace(/_/g, "/"));
    const payload = JSON.parse(jsonStr);
    if (payload.exp && Date.now() / 1000 > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}

function toHex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function fromHex(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export async function hashPassword(password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    key,
    256
  );
  return `${PBKDF2_ITERATIONS}$${toHex(salt)}$${toHex(bits)}`;
}

export async function verifyPassword(password, stored) {
  if (!stored || typeof stored !== "string") return false;
  const parts = stored.split("$");
  if (parts.length !== 3) return false;
  const iterations = Number(parts[0]);
  const salt = fromHex(parts[1]);
  const expected = parts[2];
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    key,
    256
  );
  return timingSafeEqual(toHex(bits), expected);
}

export function rateLimited(key) {
  const now = Date.now();
  const bucket = failBuckets.get(key);
  if (!bucket || now > bucket.resetAt) {
    failBuckets.set(key, { count: 1, resetAt: now + FAIL_WINDOW_MS });
    return false;
  }
  bucket.count += 1;
  return bucket.count > MAX_FAILS;
}

export function clearRateLimit(key) {
  failBuckets.delete(key);
}

export async function issueSessionJwt(user, secret) {
  const now = Math.floor(Date.now() / 1000);
  return signJwt(
    {
      typ: "session",
      sub: user.id,
      username: user.username,
      role: user.role,
      iat: now,
      exp: now + SESSION_TTL_SEC,
    },
    secret
  );
}

export function publicUser(row) {
  return {
    id: row.id,
    username: row.username,
    email: row.username,
    role: row.role,
    disabled: Boolean(row.disabled),
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

/** Email preferred; legacy short usernames (e.g. admin) still accepted. */
export function normalizeLoginId(raw) {
  const id = String(raw || "")
    .trim()
    .toLowerCase();
  if (!id || id.length > 120) return null;
  if (id.includes("@")) {
    if (!/^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(id)) return null;
    return id;
  }
  if (/^[a-z0-9._-]{2,64}$/.test(id)) return id;
  return null;
}

export function normalizeUsername(raw) {
  return normalizeLoginId(raw);
}

export function escapeLike(raw) {
  return String(raw || "").replace(/([\\%_])/g, "\\$1");
}

export async function resolveAuth(request, env) {
  const header = request.headers.get("Authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return null;

  // Bootstrap secret: migrate / admin scripts only — never for day-to-day desktop.
  const bootstrap = (env.WHM_API_TOKEN || "").trim();
  if (bootstrap && (await timingSafeEqual(token, bootstrap))) {
    return { type: "bootstrap", role: "admin", username: "bootstrap", userId: null };
  }

  const jwtSecret = (env.WHM_JWT_SECRET || "").trim();
  if (jwtSecret) {
    const payload = await verifyJwt(token, jwtSecret);
    if (payload && payload.typ === "session") {
      return {
        type: "session",
        role: payload.role,
        username: payload.username,
        userId: payload.sub,
      };
    }
  }
  return null;
}

export function roleAllowed(auth, allowed) {
  return Boolean(auth && allowed.includes(auth.role));
}

export async function ensureUsersTable(db) {
  await db
    .prepare(
      `CREATE TABLE IF NOT EXISTS users (
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
      )`
    )
    .run();
}
