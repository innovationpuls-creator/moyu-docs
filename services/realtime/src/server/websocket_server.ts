/**
 * Realtime WebSocket gateway (plan Tasks 25-26, Phase 8).
 *
 * HTTP server + ``WebSocketServer({ noServer: true })``: the upgrade handler
 * resolves the ``dom_session`` cookie, verifies it against the Valkey session
 * cache (src/auth/session_authenticator.ts) and either accepts the upgrade —
 * attaching the cached session metadata to the socket — or answers the
 * handshake with HTTP 401 before the HTTP layer completes (the ws client then
 * observes an 'unexpected-response' with statusCode 401).
 *
 * Accepted connections are registered with the SessionInvalidator, which
 * subscribes to ``events:session_invalidated`` and force-closes the socket
 * with code 4001 after sending the SessionReplaced frame when the session is
 * replaced on another device (FR-AUTH-016/017, doc 16 §80-§82).
 *
 * The gateway shares the API service's Valkey database: the default
 * ``valkeyUrl`` mirrors services/api config (redis://localhost:6379/14 in dev);
 * production must point realtime and the API at the same cache instance.
 */

import { createServer, type Server as HttpServer } from "node:http";

import { Redis } from "ioredis";
import { type WebSocket, WebSocketServer } from "ws";

import {
	type SessionCachedData,
	verifySession,
} from "../auth/session_authenticator.js";
import { SessionInvalidator } from "../connection/session_invalidator.js";

/** Cookie name — mirrors api.config settings.session_cookie ("dom_session"). */
export const SESSION_COOKIE_NAME = "dom_session";
/** A rejected upgrade gets a minimal 401 that the ws client surfaces as
 * 'unexpected-response' (statusCode 401). */
const UNAUTHORIZED_RESPONSE =
	"HTTP/1.1 401 Unauthorized\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nUnauthorized";

const DEFAULT_VALKEY_URL = "redis://localhost:6379/14";

export interface RealtimeServerHandle {
	server: HttpServer;
	/** Resolves once the invalidation pub/sub subscription is live (awaited by
	 * integration tests before firing events). */
	readonly ready: Promise<void>;
	/** Gracefully close every connection, unsubscribe and release resources. */
	close(): Promise<void>;
}

export interface RealtimeServerOptions {
	port: number;
	valkeyUrl?: string;
}

interface AuthenticatedWebSocket extends WebSocket {
	session: SessionCachedData;
}

/** Parse the value of a named cookie from an HTTP Cookie header (RFC 6265
 * token, percent-decoded). Returns null when absent or malformed. */
export function parseCookieHeader(
	header: string | undefined,
	name: string,
): string | null {
	if (!header) {
		return null;
	}
	for (const part of header.split(";")) {
		const eq = part.indexOf("=");
		if (eq === -1) {
			continue;
		}
		if (part.slice(0, eq).trim() !== name) {
			continue;
		}
		const raw = part.slice(eq + 1).trim();
		try {
			return decodeURIComponent(raw);
		} catch {
			return raw;
		}
	}
	return null;
}

export function startRealtimeServer({
	port,
	valkeyUrl = DEFAULT_VALKEY_URL,
}: RealtimeServerOptions): RealtimeServerHandle {
	const valkey = new Redis(valkeyUrl);
	const invalidator = new SessionInvalidator(valkey);
	const server = createServer();
	const wss = new WebSocketServer({ noServer: true });

	// Begin the invalidation subscription immediately; `ready` resolves when
	// it is live. A failure here also means auth lookups fail, so log it and
	// keep the promise rejectable for callers that await `ready`.
	const ready = invalidator.start();
	ready.catch((error: unknown) => {
		console.error(
			"[dom/realtime] session-invalidator subscribe failed:",
			error,
		);
	});

	server.on("upgrade", (request, socket, head) => {
		void (async () => {
			// Ensure the pub/sub subscription is live before accepting ANY
			// connection (idempotent): a socket must never be accepted before
			// it could receive an invalidation event.
			await invalidator.start();
			const cookieValue = parseCookieHeader(
				request.headers.cookie,
				SESSION_COOKIE_NAME,
			);
			const session =
				cookieValue === null ? null : await verifySession(cookieValue, valkey);
			// Defense-in-depth: the cached payload's session_id must match the
			// cookie used to look it up.
			if (session === null || session.session_id !== cookieValue) {
				socket.write(UNAUTHORIZED_RESPONSE);
				socket.destroy();
				return;
			}
			wss.handleUpgrade(request, socket, head, (ws) => {
				const authenticated = ws as AuthenticatedWebSocket;
				authenticated.session = session;
				wss.emit("connection", authenticated, request);
			});
		})().catch(() => {
			// Verification could not complete (e.g. transient Valkey error):
			// reject rather than accept an unverified connection.
			socket.write(UNAUTHORIZED_RESPONSE);
			socket.destroy();
		});
	});

	wss.on("connection", (ws) => {
		const authenticated = ws as AuthenticatedWebSocket;
		const session = authenticated.session;
		if (session === undefined) {
			// Only reachable if a non-upgrade path emitted 'connection'.
			ws.close(4401, "session missing");
			return;
		}
		const unregister = invalidator.register(session.session_id, ws);
		ws.on("close", () => {
			unregister();
		});
		ws.on("error", () => {
			// Socket-level errors close the socket; the 'close' handler above
			// unregisters. No business action to take.
		});
	});

	const close = async (): Promise<void> => {
		for (const client of wss.clients) {
			client.close(1001, "server shutting down");
		}
		// Let the subscription settle before tearing the pub/sub connection
		// down; otherwise a still-pending subscribe would be flushed with the
		// disconnect error (rejection noise / missed unsubscribe).
		await ready.catch(() => {});
		await invalidator.close();
		await new Promise<void>((resolve) => {
			wss.close(() => resolve());
		});
		await new Promise<void>((resolve) => {
			server.close(() => resolve());
		});
		valkey.disconnect();
	};

	server.listen(port);
	return { server, ready, close };
}
