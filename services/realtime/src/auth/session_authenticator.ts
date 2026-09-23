/**
 * Session authentication for the realtime WebSocket gateway (plan Task 25 §4).
 *
 * Verifies a WebSocket-handshake ``dom_session`` cookie against the Valkey
 * session cache that the API layer maintains — key ``session:{session_id}``,
 * JSON payload, 5s TTL (contract: packages/py/infrastructure/src/app_infra/
 * valkey/session_cache.py). The cache is the fast path; PostgreSQL remains the
 * authority (doc 16 §79/§125) and the API re-validates on every protected
 * request. For a short-lived realtime connection the cache is the appropriate
 * source: the 5s TTL bounds staleness (doc 16 §80) and a freshly replaced /
 * expired session is rejected at the handshake.
 */

import type { Redis } from "ioredis";

export const SESSION_CACHE_KEY_PREFIX = "session:";
export const SESSION_CACHE_STATUS_ACTIVE = "Active";

/**
 * Cached-session payload (mirror of app_core.session.ports.session_cache
 * SessionCachedData). Datetimes are ISO-8601 strings written by the Python
 * adapter (datetime.isoformat() round-trip).
 */
export interface SessionCachedData {
	session_id: string;
	account_id: string;
	device_id: string;
	status: string;
	expires_at: string;
	last_strong_auth_at: string;
}

/**
 * Clock-skew allowance: a session up to this far past its ``expires_at`` still
 * authenticates. 5s matches the cache TTL bound and avoids flaky handshakes
 * when the realtime instance and the API run on hosts whose clocks differ by
 * milliseconds around the exact expiry instant. Security impact is nil: the
 * authoritative API re-validates against PostgreSQL with no skew.
 */
export const EXPIRY_SKEW_MS = 5_000;

/** Verify a session cookie against the Valkey session cache. Returns the
 * cached payload for an Active, not-yet-expired session, else null (caller
 * rejects the handshake). Null on a missing / corrupt / inactive / expired
 * entry — a corrupt entry is a miss, mirroring the Python adapter's
 * disposable-cache fallback. */
export async function verifySession(
	sessionId: string,
	valkey: Redis,
	now: Date = new Date(),
): Promise<SessionCachedData | null> {
	if (sessionId.length === 0) {
		return null;
	}
	const raw = await valkey.get(`${SESSION_CACHE_KEY_PREFIX}${sessionId}`);
	if (raw === null) {
		return null;
	}
	let payload: SessionCachedData;
	try {
		payload = JSON.parse(raw) as SessionCachedData;
	} catch {
		return null;
	}
	if (payload.status !== SESSION_CACHE_STATUS_ACTIVE) {
		return null;
	}
	const expiresAt = new Date(payload.expires_at);
	if (Number.isNaN(expiresAt.getTime())) {
		return null;
	}
	if (expiresAt.getTime() + EXPIRY_SKEW_MS < now.getTime()) {
		return null;
	}
	return payload;
}
