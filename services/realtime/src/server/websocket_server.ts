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
import {
	decodeRealtimeBinaryFrame,
	encodeRealtimeBinaryFrame,
} from "@dom/realtime-protocol";
import { Redis } from "ioredis";
import { type RawData, type WebSocket, WebSocketServer } from "ws";

import {
	type SessionCachedData,
	verifySession,
} from "../auth/session_authenticator.js";
import type { PresenceStore } from "../backlog/presence_store.js";
import {
	MemoryPresenceStore,
	ValkeyPresenceStore,
} from "../backlog/presence_store.js";
import type { YjsBacklogStore } from "../backlog/yjs_backlog_store.js";
import {
	MemoryYjsBacklogStore,
	ValkeyYjsBacklogStore,
} from "../backlog/yjs_backlog_store.js";
import { SessionInvalidator } from "../connection/session_invalidator.js";
import { GatewayRelayHost } from "../relay/gateway_relay_host.js";

/** Cookie name — mirrors api.config settings.session_cookie ("dom_session"). */
export const SESSION_COOKIE_NAME = "dom_session";
/** A rejected upgrade gets a minimal 401 that the ws client surfaces as
 * 'unexpected-response' (statusCode 401). */
const UNAUTHORIZED_RESPONSE =
	"HTTP/1.1 401 Unauthorized\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nUnauthorized";

const DEFAULT_VALKEY_URL = "redis://localhost:6379/14";

function toUint8Array(data: RawData): Uint8Array {
	if (Buffer.isBuffer(data))
		return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
	if (data instanceof ArrayBuffer) return new Uint8Array(data);
	return new Uint8Array(Buffer.concat(data));
}

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

	let connectionSeq = 0;
	wss.on("connection", (ws) => {
		const authenticated = ws as AuthenticatedWebSocket;
		const session = authenticated.session;
		if (session === undefined) {
			// Only reachable if a non-upgrade path emitted 'connection'.
			ws.close(4401, "session missing");
			return;
		}
		// Server-wide sequence: the SAME account opens multiple tabs (sessions
		// share session_id), so the connection id must stay unique per socket.
		const connectionId = `${session.session_id}:${connectionSeq++}`;
		relayHost.registerConnection(connectionId, (envelope) => {
			if (ws.readyState === ws.OPEN) {
				const message = envelope as {
					kind?: string;
					resourceId?: string;
					subscriptionId?: string;
					payload?: unknown;
				};
				const payload = message.payload as
					| { kind?: string; update?: string }
					| undefined;
				if (
					message.kind === "op" &&
					message.resourceId &&
					payload?.kind === "yjs" &&
					typeof payload.update === "string"
				) {
					ws.send(
						encodeRealtimeBinaryFrame(
							{
								messageType: "sync.update",
								resourceId: message.resourceId,
								subscriptionId: message.subscriptionId ?? "",
							},
							new Uint8Array(Buffer.from(payload.update, "base64")),
						),
					);
					return;
				}
				ws.send(JSON.stringify({ protocolVersion: 1, ...message }));
			}
		});
		const unregister = invalidator.register(session.session_id, ws);
		ws.on("close", () => {
			unregister();
			relayHost.unregisterConnection(connectionId);
		});
		ws.on("error", () => {
			// Socket-level errors close the socket; the 'close' handler above
			// unregisters. No business action to take.
		});
		ws.on("message", (data, isBinary) => {
			if (isBinary) {
				let frame: ReturnType<typeof decodeRealtimeBinaryFrame>;
				try {
					frame = decodeRealtimeBinaryFrame(toUint8Array(data));
				} catch {
					ws.close(4400, "malformed binary frame");
					return;
				}
				const { header, payload } = frame;
				if (
					!relayHost.manager.isSubscribed(
						connectionId,
						header.resourceId,
						header.subscriptionId,
					)
				) {
					ws.close(4403, "resource subscription required");
					return;
				}
				if (header.messageType === "sync.state-vector") {
					void relayHost.manager
						.incrementalSync(
							connectionId,
							header.resourceId,
							Buffer.from(payload).toString("base64"),
						)
						.catch((error: unknown) => {
							console.error("[dom/realtime] state-vector sync failed", error);
						});
					return;
				}
				const update = Buffer.from(payload).toString("base64");
				void relayHost.manager
					.publishYjsUpdate(
						connectionId,
						header.resourceId,
						header.subscriptionId,
						update,
					)
					.catch((error: unknown) => {
						console.error("[dom/realtime] Yjs update publish failed", error);
					});
				return;
			}
			let message: {
				type?: string;
				resourceId?: string;
				subscriptionId?: string;
				protocolVersion?: number;
				payload?: unknown;
			};
			try {
				message = JSON.parse(data.toString()) as {
					type?: string;
					resourceId?: string;
					subscriptionId?: string;
					protocolVersion?: number;
					payload?: unknown;
				};
			} catch {
				ws.close(4400, "malformed message");
				return;
			}
			if (
				message.protocolVersion !== undefined &&
				message.protocolVersion !== 1
			) {
				ws.close(4400, "unsupported protocol version");
				return;
			}
			if (message.type === "unsubscribe" && message.resourceId) {
				relayHost.manager.unsubscribe(
					connectionId,
					message.resourceId,
					message.subscriptionId,
				);
				return;
			}
			if (
				message.type === "op" &&
				message.resourceId &&
				relayHost.manager.isSubscribed(
					connectionId,
					message.resourceId,
					message.subscriptionId,
				)
			) {
				// Peer op relay (arch 05 §171): client-originated Yjs updates go
				// to the OTHER subscribers of the same resource; the origin
				// excludes itself (it already applied the local update).
				if (
					typeof message.payload === "object" &&
					message.payload !== null &&
					(message.payload as { kind?: string }).kind === "sync" &&
					typeof (message.payload as { stateVector?: string }).stateVector ===
						"string"
				) {
					void relayHost.manager
						.incrementalSync(
							connectionId,
							message.resourceId,
							(message.payload as { stateVector: string }).stateVector,
						)
						.catch((err: unknown) => {
							console.error("[dom/realtime] sync failed", err);
						});
				}
				if (
					typeof message.payload === "object" &&
					message.payload !== null &&
					(message.payload as { kind?: string }).kind === "yjs"
				) {
					const update = (message.payload as { update?: unknown }).update;
					if (typeof update === "string") {
						const activeSubscriptionId = relayHost.manager.getSubscriptionId(
							connectionId,
							message.resourceId,
						);
						void relayHost.manager
							.publishYjsUpdate(
								connectionId,
								message.resourceId,
								activeSubscriptionId,
								update,
							)
							.catch((error: unknown) => {
								console.error(
									"[dom/realtime] Yjs update publish failed",
									error,
								);
							});
					}
					return;
				}
				void relayHost.manager.dispatch(
					message.resourceId,
					{
						kind: "op",
						payload: message.payload,
					},
					connectionId,
				);
				return;
			}
			if (message.type === "subscribe" && message.resourceId) {
				void relayHost.manager
					.subscribe(
						connectionId,
						session.session_id,
						message.resourceId,
						message.subscriptionId,
					)
					.then((result) => {
						if (result === "denied" && ws.readyState === ws.OPEN) {
							ws.send(
								JSON.stringify({
									protocolVersion: 1,
									resourceId: message.resourceId,
									subscriptionId: message.subscriptionId,
									kind: "subscribe",
									payload: { status: "denied" },
								}),
							);
						}
					});
				return;
			}
		});
	});

	// Yjs backlog (arch 05 §initial sync): Valkey-backed when configured so
	// catch-up survives gateway restarts; in-memory otherwise.
	const backlogStore: YjsBacklogStore = process.env.REDIS_BACKLOG_URL
		? new ValkeyYjsBacklogStore(valkey)
		: new MemoryYjsBacklogStore();
	const presenceStore: PresenceStore = process.env.REDIS_BACKLOG_URL
		? new ValkeyPresenceStore(valkey)
		: new MemoryPresenceStore();
	// Realtime op relay: NATS broadcasts -> subscribed connections.
	const relayHost = new GatewayRelayHost({
		apiBaseUrl: process.env.REALTIME_API_BASE_URL ?? "http://127.0.0.1:8000",
		natsUrl: process.env.NATS_URL ?? "nats://localhost:4222",
		backlogStore,
		presenceStore,
	});
	relayHost.startRelay().catch((error: unknown) => {
		console.error("[dom/realtime] relay start failed:", error);
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
