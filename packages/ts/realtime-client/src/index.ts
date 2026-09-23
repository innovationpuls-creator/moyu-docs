/**
 * Minimal WebSocket client for the DOM realtime gateway (doc 27 §17).
 *
 * WebSocket creation lives ONLY here — feature pages never construct a
 * WebSocket themselves. The client connects with the ambient browser cookie
 * jar (the ``dom_session`` cookie is host-scoped, so the gateway on the same
 * host receives it) and translates the gateway's SessionReplaced control
 * signal (FR-AUTH-016/017):
 *
 * - while open, any message whose JSON parses to ``type: "SessionReplaced"``
 *   is remembered as the replacement frame;
 * - a close with code ``4001`` (SESSION_REPLACED_CLOSE_CODE) dispatches a DOM
 *   ``sessionreplaced`` CustomEvent on ``window`` (detail carries the frame +
 *   closeCode) and invokes registered listeners; every other close is a plain
 *   disconnect and does NOT trigger the replacement flow.
 *
 * Typed by @dom/contracts: the domain envelope for the event is
 * ``session-replaced.d.ts`` (SessionReplaced / SessionReplacementReason); the
 * gateway's wire frame is a lightweight projection of that envelope, so the
 * client maps the wire ``reason`` onto the generated
 * ``SessionReplacementReason`` union.
 */

import type { SessionReplacementReason } from "@dom/contracts/events/auth/session-replaced";

/** Close code the gateway uses for auth-forced replacement (services/realtime
 * src/connection/session_invalidator.ts SESSION_REPLACED_CLOSE_CODE). */
export const SESSION_REPLACED_CLOSE_CODE = 4001;

/** DOM event name dispatched on window when a session was replaced. */
export const SESSION_REPLACED_EVENT = "sessionreplaced";

/** Gateway wire frame (projection of the generated SessionReplaced envelope;
 * mirrors services/realtime SessionReplacedFrame). */
export interface SessionReplacedFrame {
	type: "SessionReplaced";
	reason: string;
	message: string;
}

export interface SessionReplacedDetail {
	closeCode: number;
	frame: SessionReplacedFrame;
	/** Mapped onto the generated union; unknown wire reasons -> SecurityRevoke
	 * (mirrors the gateway's own fallback). */
	reason: SessionReplacementReason;
	message: string;
}

export interface RealtimeClient {
	readonly socket: WebSocket;
	/** Subscribe to the session-replaced transition; returns unsubscribe. */
	onSessionReplaced(
		listener: (detail: SessionReplacedDetail) => void,
	): () => void;
	/** Close the socket (plain 1000/1001 close — no replacement dispatch). */
	close(): void;
}

function toReplacementReason(reason: string): SessionReplacementReason {
	const reasons: readonly SessionReplacementReason[] = [
		"NewDeviceLogin",
		"UserLogout",
		"PasswordReset",
		"AccountDisabled",
		"Expired",
		"SecurityRevoke",
	];
	return (reasons as readonly string[]).includes(reason)
		? (reason as SessionReplacementReason)
		: "SecurityRevoke";
}

function parseFrame(raw: string): SessionReplacedFrame | null {
	try {
		const value = JSON.parse(raw) as unknown;
		if (
			typeof value === "object" &&
			value !== null &&
			(value as { type?: unknown }).type === "SessionReplaced"
		) {
			return value as SessionReplacedFrame;
		}
	} catch {
		// Not JSON or not a control frame — ignore.
	}
	return null;
}

/** Connect to the realtime gateway. The browser sends the session cookie on
 * the handshake automatically (same host); ``onSessionReplaced`` replaces the
 * need for any feature-level socket inspection. The socket is opened
 * immediately; callers that fail fast (e.g. 401 unexpected-response) should
 * listen for ``error``/``close`` on the returned socket. */
export function connectRealtime(url: string): RealtimeClient {
	const socket = new WebSocket(url);
	const listeners = new Set<(detail: SessionReplacedDetail) => void>();
	let lastFrame: SessionReplacedFrame | null = null;

	socket.addEventListener("message", (event: MessageEvent<string>) => {
		const frame = parseFrame(event.data);
		if (frame !== null) {
			lastFrame = frame;
		}
	});
	socket.addEventListener("close", (event: CloseEvent) => {
		if (event.code !== SESSION_REPLACED_CLOSE_CODE) {
			return;
		}
		const frame = lastFrame ?? {
			type: "SessionReplaced" as const,
			reason: "SecurityRevoke",
			message: "当前账号已在另一台设备登录，本设备已下线",
		};
		const detail: SessionReplacedDetail = {
			closeCode: event.code,
			frame,
			reason: toReplacementReason(frame.reason),
			message: frame.message,
		};
		for (const listener of listeners) {
			listener(detail);
		}
		window.dispatchEvent(
			new CustomEvent<SessionReplacedDetail>(SESSION_REPLACED_EVENT, {
				detail,
			}),
		);
	});

	return {
		socket,
		onSessionReplaced(listener) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
		close() {
			socket.close();
		},
	};
}
