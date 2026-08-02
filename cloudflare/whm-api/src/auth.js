/**
 * Username/password + TOTP MFA + JWT session helpers for WHM Worker.
 */

// Workers CPU budget: keep iterations high enough for desktop secrets, low enough for D1 edge.
const PBKDF2_ITERATIONS = 100000;
const SESSION_TTL_SEC = 12 * 60 * 60; // 12 hours
const MFA_TEMP_TTL_SEC = 5 * 60; // 5 minutes
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
  const expected = b64url(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data)));
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

const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

export function generateTotpSecret(bytes = 20) {
  const arr = crypto.getRandomValues(new Uint8Array(bytes));
  let bits = "";
  for (const b of arr) bits += b.toString(2).padStart(8, "0");
  let out = "";
  for (let i = 0; i < bits.length; i += 5) {
    const chunk = bits.slice(i, i + 5);
    if (chunk.length < 5) break;
    out += BASE32_ALPHABET[parseInt(chunk, 2)];
  }
  return out;
}

function base32Decode(secret) {
  const clean = String(secret || "")
    .toUpperCase()
    .replace(/=+$/g, "")
    .replace(/[^A-Z2-7]/g, "");
  let bits = "";
  for (const ch of clean) {
    const val = BASE32_ALPHABET.indexOf(ch);
    if (val < 0) continue;
    bits += val.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return new Uint8Array(bytes);
}

async function hotp(secretBytes, counter) {
  const buf = new ArrayBuffer(8);
  const view = new DataView(buf);
  // big-endian 64-bit counter (high 32 always 0 for JS safe ints)
  view.setUint32(0, Math.floor(counter / 0x100000000), false);
  view.setUint32(4, counter >>> 0, false);
  const key = await crypto.subtle.importKey(
    "raw",
    secretBytes,
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"]
  );
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, buf));
  const offset = sig[sig.length - 1] & 0x0f;
  const code =
    ((sig[offset] & 0x7f) << 24) |
    ((sig[offset + 1] & 0xff) << 16) |
    ((sig[offset + 2] & 0xff) << 8) |
    (sig[offset + 3] & 0xff);
  return String(code % 1_000_000).padStart(6, "0");
}

export async function verifyTotp(secret, code, { window = 1, lastStep = null } = {}) {
  const digits = String(code || "").replace(/\s/g, "");
  if (!/^\d{6}$/.test(digits)) return { ok: false, step: null };
  const secretBytes = base32Decode(secret);
  if (!secretBytes.length) return { ok: false, step: null };
  const step = Math.floor(Date.now() / 1000 / 30);
  for (let w = -window; w <= window; w++) {
    const candidateStep = step + w;
    if (lastStep != null && candidateStep <= lastStep) continue;
    const expected = await hotp(secretBytes, candidateStep);
    if (await timingSafeEqual(expected, digits)) {
      return { ok: true, step: candidateStep };
    }
  }
  return { ok: false, step: null };
}

export function otpauthUri(username, secret, issuer = "Website Health Manager") {
  const label = encodeURIComponent(`${issuer}:${username}`);
  const params = new URLSearchParams({
    secret,
    issuer,
    algorithm: "SHA1",
    digits: "6",
    period: "30",
  });
  return `otpauth://totp/${label}?${params.toString()}`;
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

export async function issueMfaTempJwt(user, secret, purpose) {
  const now = Math.floor(Date.now() / 1000);
  return signJwt(
    {
      typ: purpose,
      sub: user.id,
      username: user.username,
      role: user.role,
      iat: now,
      exp: now + MFA_TEMP_TTL_SEC,
    },
    secret
  );
}

export function publicUser(row) {
  return {
    id: row.id,
    username: row.username,
    role: row.role,
    totp_enabled: Boolean(row.totp_enabled),
    disabled: Boolean(row.disabled),
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

/** Safe username: letters, digits, . _ - only (blocks injection / weird control chars). */
export function normalizeUsername(raw) {
  const username = String(raw || "")
    .trim()
    .toLowerCase();
  if (!/^[a-z0-9._-]{2,64}$/.test(username)) return null;
  return username;
}

/** Escape LIKE metacharacters when binding user search text. */
export function escapeLike(raw) {
  return String(raw || "").replace(/([\\%_])/g, "\\$1");
}

export async function resolveAuth(request, env) {
  const header = request.headers.get("Authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return null;

  const bootstrap = (env.WHM_API_TOKEN || "").trim();
  if (bootstrap && (await timingSafeEqual(token, bootstrap))) {
    return { type: "bootstrap", role: "admin", username: "bootstrap", userId: null };
  }

  const jwtSecret = (env.WHM_JWT_SECRET || "").trim();
  if (!jwtSecret) return null;
  const payload = await verifyJwt(token, jwtSecret);
  if (!payload || payload.typ !== "session") return null;
  return {
    type: "session",
    role: payload.role,
    username: payload.username,
    userId: payload.sub,
  };
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
