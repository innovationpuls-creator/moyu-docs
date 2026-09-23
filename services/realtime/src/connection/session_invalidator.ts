/**
 * Session-invalidation consumer (plan Task 26).
 *
 * Each realtime instance keeps a local registry of live WebSocket connections
 * keyed by sessionId and subscribes to the shared Valkey pubsub channel
 * ``events:session_invalidated`` — the same channel the API's
 * ValkeySessionCache publishes to on login replacement, logout and revocations
 * (packages/py/infrastructure/src/app_infra/valkey/session_cache.py;
 * FR-AUTH-015/016, doc 16 §80-§82, doc 29 §21). On an event whose session_id
 * matches a live connection, the consumer sends the client-facing
 * ``SessionReplaced`` frame (BDD FR-AUTH-016/017) and closes the socket with
 * code 4001 so the client can distinguish an auth-forced close from a network
 * drop.
 *
 * Pub/sub lifecycle: ioredis requires a dedicated connection for subscribe
 * (subscribe blocks other commands on that connection), so the invalidator
 * owns a ``valkey.duplicate()`` connection; ``start()`` subscribes, ``close()``
 * unsubscribes and disconnects it.
 */

import type { SessionReplacementReason } from "@dom/contracts/events/auth/session-replaced";
import type { Redis } from "ioredis";
import { WebSocket } from "ws";

export const SESSION_INVALIDATION_CHANNEL = "events:session_invalidated";
export const SESSION_REPLACED_CLOSE_CODE = 4001;
export const SESSION_REPLACED_MESSAGE = "当前账号已在另一台设备登录";

/**
 * Client-facing SessionReplaced frame (BDD FR-AUTH-016/017). The full domain
 * envelope lives in the generated contracts (packages/ts/contracts/src/events/
 * auth/session-replaced.d.ts, doc 28 §22 + §25); the wire frame is a
 * lightweight projection: type + reason + user-facing message. ``reason`` is
 * the generated ``SessionReplacementReason`` union, imported from
 * @dom/contracts (re-exported here so the module's public surface is
 * unchanged for consumers that imported the name).
 */
export type { SessionReplacementReason } from "@dom/contracts/events/auth/session-replaced";

export const SESSION_REPLACEMENT_REASONS: readonly SessionReplacementReason[] =
	[
		"NewDeviceLogin",
		"UserLogout",
		"PasswordReset",
		"AccountDisabled",
		"Expired",
		"SecurityRevoke",
	];

function isSessionReplacementReason(
	value: string,
): value is SessionReplacementReason {
	return (SESSION_REPLACEMENT_REASONS as readonly string[]).includes(value);
}

export interface SessionReplacedFrame {
	type: "SessionReplaced";
	reason: SessionReplacementReason;
	message: string;
}

/** Pubsub payload published by the API layer (ValkeySessionCache
 * publish_invalidation / invalidate_session). ``reason`` is null when the
 * caller could not name the cause (invalidate_session path). */
export interface SessionInvalidationEvent {
	session_id: string;
	reason: string | null;
}

/** Minimal structural socket surface the invalidator needs. A real
 * ``ws`` WebSocket satisfies it; tests may pass a harness stub (e.g.
 * vi.fn() send/close) without casts. */
export interface InvalidatableSocket {
	readonly readyState: number;
	send(data: string): void;
	close(code?: number): void;
}

export class SessionInvalidator {
	private readonly connections = new Map<string, Set<InvalidatableSocket>>();
	private readonly subscriber: Redis;
	private readonly onMessage: (channel: string, message: string) => void;
	private started = false;
	private startPromise: Promise<void> | null = null;

	constructor(valkey: Redis) {
		// ioredis pub/sub needs its own connection. lazyConnect + an explicit
		// connect() in start() avoids a known ioredis race where a SUBSCRIBE
		// queued before the handshake completes flushes ahead of the 'info'
		// handshake command, which Redis then rejects ("only subscribe
		// commands allowed in this context" / "Connection in subscriber
		// mode").
		this.subscriber = valkey.duplicate({ lazyConnect: true });
		this.onMessage = (channel, message) => {
			if (channel !== SESSION_INVALIDATION_CHANNEL) {
				return;
			}
			let event: SessionInvalidationEvent;
			try {
				event = JSON.parse(message) as SessionInvalidationEvent;
			} catch {
				// A malformed event is dropped; the cache TTL still bounds
				// staleness for any affected connection.
				return;
			}
			const sockets = this.connections.get(event.session_id);
			if (sockets === undefined) {
				return;
			}
			const reason: SessionReplacementReason =
				event.reason !== null && isSessionReplacementReason(event.reason)
					? event.reason
					: "SecurityRevoke";
			const frame = JSON.stringify({
				type: "SessionReplaced",
				reason,
				message: SESSION_REPLACED_MESSAGE,
			} satisfies SessionReplacedFrame);
			for (const socket of sockets) {
				if (socket.readyState === WebSocket.OPEN) {
					socket.send(frame);
					socket.close(SESSION_REPLACED_CLOSE_CODE);
				}
			}
		};
	}

	/** Subscribe to the invalidation channel. Idempotent and single-flight
	 * (concurrent callers share one connection + subscribe). */
	start(): Promise<void> {
		if (this.started) {
			return Promise.resolve();
		}
		if (this.startPromise !== null) {
			return this.startPromise;
		}
		this.startPromise = this.doStart();
		return this.startPromise;
	}

	private async doStart(): Promise<void> {
		// Complete the full connect handshake (incl. 'info') BEFORE the first
		// SUBSCRIBE, so the handshake never runs on a subscriber-mode
		// connection.
		try {
			await this.subscriber.connect();
			await this.subscriber.subscribe(SESSION_INVALIDATION_CHANNEL);
			this.subscriber.on("message", this.onMessage);
			this.started = true;
		} catch (error) {
			// Clear the single-flight so a LATER start() call retries (e.g.
			// after Valkey recovers); the rejection itself propagates to the
			// current caller, who rejects the affected handshakes.
			this.startPromise = null;
			throw error;
		}
	}

	/** Register a live connection; returns an unregister callback (call on
	 * socket close so the registry never holds closed sockets). */
	register(sessionId: string, socket: InvalidatableSocket): () => void {
		let set = this.connections.get(sessionId);
		if (set === undefined) {
			set = new Set();
			this.connections.set(sessionId, set);
		}
		set.add(socket);
		return () => {
			const current = this.connections.get(sessionId);
			if (current === undefined) {
				return;
			}
			current.delete(socket);
			if (current.size === 0) {
				this.connections.delete(sessionId);
			}
		};
	}

	/** Unsubscribe, disconnect the pub/sub connection and drop the registry. */
	async close(): Promise<void> {
		if (this.started) {
			this.subscriber.off("message", this.onMessage);
			await this.subscriber.unsubscribe(SESSION_INVALIDATION_CHANNEL);
		}
		this.subscriber.disconnect();
		this.connections.clear();
	}
}
