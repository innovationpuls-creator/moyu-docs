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
import {
	decodeRealtimeBinaryFrame,
	encodeRealtimeBinaryFrame,
	type SyncMessageType,
} from "@dom/realtime-protocol";

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

export type RealtimeConnectionState =
	| "connecting"
	| "connected"
	| "disconnected"
	| "replaced";

export interface ResourceRealtimeHandlers {
	getStateVector(): Uint8Array;
	getLocalState(): Uint8Array;
	onUpdate(update: Uint8Array): void;
	onPeers(count: number): void;
	onStatus(state: RealtimeConnectionState | "denied"): void;
}

export interface ResourceRealtimeClient {
	subscribeResource(
		resourceId: string,
		handlers: ResourceRealtimeHandlers,
	): () => void;
	publishUpdate(resourceId: string, update: Uint8Array): void;
	requestStateVector(resourceId: string, vector: Uint8Array): void;
	onConnectionState(
		listener: (state: RealtimeConnectionState) => void,
	): () => void;
	onSessionReplaced(
		listener: (detail: SessionReplacedDetail) => void,
	): () => void;
	close(): void;
}

interface ResourceSubscription {
	subscriptionId: string;
	handlers: ResourceRealtimeHandlers;
}

interface RealtimeSocket {
	readyState: number;
	addEventListener(type: string, listener: (event: never) => void): void;
	send(data: string | Uint8Array): void;
	close(code?: number, reason?: string): void;
}

type RealtimeSocketFactory = (url: string) => RealtimeSocket;

const SOCKET_OPEN = 1;
const SOCKET_CONNECTING = 0;

/** Shared resource transport. Feature code receives typed events and binary Yjs updates only. */
export class ManagedResourceRealtimeClient implements ResourceRealtimeClient {
	private socket: RealtimeSocket | null = null;
	private readonly subscriptions = new Map<string, ResourceSubscription>();
	private readonly stateListeners = new Set<
		(state: RealtimeConnectionState) => void
	>();
	private readonly replacementListeners = new Set<
		(detail: SessionReplacedDetail) => void
	>();
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private retryDelay = 500;
	private manuallyClosed = false;
	private connectionState: RealtimeConnectionState = "disconnected";
	private lastReplacement: SessionReplacedFrame | null = null;

	constructor(
		private readonly url: string,
		private readonly socketFactory: RealtimeSocketFactory = (target) =>
			new WebSocket(target) as unknown as RealtimeSocket,
	) {
		this.open();
	}

	subscribeResource(
		resourceId: string,
		handlers: ResourceRealtimeHandlers,
	): () => void {
		const previous = this.subscriptions.get(resourceId);
		if (previous) {
			this.sendControl("unsubscribe", resourceId, previous.subscriptionId);
		}
		const subscription = { subscriptionId: crypto.randomUUID(), handlers };
		this.subscriptions.set(resourceId, subscription);
		handlers.onStatus(this.connectionState);
		if (this.connectionState === "connected") {
			this.sendControl("subscribe", resourceId, subscription.subscriptionId);
		}
		return () => {
			if (this.subscriptions.get(resourceId) !== subscription) return;
			this.sendControl("unsubscribe", resourceId, subscription.subscriptionId);
			this.subscriptions.delete(resourceId);
		};
	}

	publishUpdate(resourceId: string, update: Uint8Array): void {
		this.sendBinary(resourceId, "sync.update", update);
	}

	requestStateVector(resourceId: string, vector: Uint8Array): void {
		this.sendBinary(resourceId, "sync.state-vector", vector);
	}

	onConnectionState(
		listener: (state: RealtimeConnectionState) => void,
	): () => void {
		this.stateListeners.add(listener);
		listener(this.connectionState);
		return () => this.stateListeners.delete(listener);
	}

	onSessionReplaced(
		listener: (detail: SessionReplacedDetail) => void,
	): () => void {
		this.replacementListeners.add(listener);
		return () => this.replacementListeners.delete(listener);
	}

	close(): void {
		this.manuallyClosed = true;
		if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
		this.reconnectTimer = null;
		this.socket?.close(1000, "client closed");
		this.socket = null;
		this.setConnectionState("disconnected");
	}

	private open(): void {
		if (this.manuallyClosed) return;
		this.setConnectionState("connecting");
		let socket: RealtimeSocket;
		try {
			socket = this.socketFactory(this.url);
		} catch {
			this.setConnectionState("disconnected");
			this.scheduleReconnect();
			return;
		}
		this.socket = socket;
		socket.addEventListener("open", (() => {
			if (this.socket !== socket) return;
			this.retryDelay = 500;
			this.setConnectionState("connected");
			for (const [resourceId, subscription] of this.subscriptions) {
				this.sendControl("subscribe", resourceId, subscription.subscriptionId);
			}
		}) as never);
		socket.addEventListener("message", ((event: MessageEvent) => {
			if (this.socket === socket) void this.receive(event.data);
		}) as never);
		socket.addEventListener("close", ((event: CloseEvent) => {
			if (this.socket !== socket) return;
			this.socket = null;
			if (event.code === SESSION_REPLACED_CLOSE_CODE) {
				this.setConnectionState("replaced");
				const frame = this.lastReplacement ?? {
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
				for (const listener of this.replacementListeners) listener(detail);
				if (typeof window !== "undefined") {
					window.dispatchEvent(
						new CustomEvent<SessionReplacedDetail>(SESSION_REPLACED_EVENT, {
							detail,
						}),
					);
				}
				return;
			}
			this.setConnectionState("disconnected");
			this.scheduleReconnect();
		}) as never);
		socket.addEventListener("error", (() => {
			if (this.socket === socket && socket.readyState === SOCKET_CONNECTING) {
				this.setConnectionState("disconnected");
			}
		}) as never);
	}

	private async receive(data: unknown): Promise<void> {
		if (typeof data === "string") {
			this.receiveControl(data);
			return;
		}
		const bytes =
			data instanceof ArrayBuffer
				? new Uint8Array(data)
				: data instanceof Uint8Array
					? data
					: data instanceof Blob
						? new Uint8Array(await data.arrayBuffer())
						: null;
		if (!bytes) return;
		try {
			const frame = decodeRealtimeBinaryFrame(bytes);
			const subscription = this.subscriptions.get(frame.header.resourceId);
			if (
				subscription &&
				frame.header.subscriptionId === subscription.subscriptionId
			) {
				if (frame.header.messageType === "sync.update") {
					subscription.handlers.onUpdate(frame.payload);
				}
			}
		} catch {
			this.socket?.close(4400, "invalid binary frame");
		}
	}

	private receiveControl(data: string): void {
		let message: {
			type?: string;
			kind?: string;
			resourceId?: string;
			protocolVersion?: number;
			payload?: unknown;
		};
		try {
			message = JSON.parse(data) as typeof message;
		} catch {
			this.socket?.close(4400, "malformed control frame");
			return;
		}
		if (
			message.protocolVersion !== undefined &&
			message.protocolVersion !== 1
		) {
			this.socket?.close(4400, "unsupported protocol version");
			return;
		}
		if (message.type === "SessionReplaced") {
			this.lastReplacement = message as unknown as SessionReplacedFrame;
			return;
		}
		if (!message.resourceId) return;
		const subscription = this.subscriptions.get(message.resourceId);
		if (!subscription) return;
		const payload =
			typeof message.payload === "object" && message.payload !== null
				? (message.payload as Record<string, unknown>)
				: {};
		if (message.kind === "subscribe" && payload.status === "ok") {
			subscription.handlers.onStatus("connected");
			this.requestStateVector(
				message.resourceId,
				subscription.handlers.getStateVector(),
			);
			this.publishUpdate(
				message.resourceId,
				subscription.handlers.getLocalState(),
			);
		} else if (message.kind === "subscribe" && payload.status === "denied") {
			subscription.handlers.onStatus("denied");
		} else if (message.kind === "op" && payload.kind === "roster") {
			subscription.handlers.onPeers(Number(payload.peers ?? 0));
		}
	}

	private sendControl(
		type: "subscribe" | "unsubscribe",
		resourceId: string,
		subscriptionId: string,
	): void {
		if (this.socket?.readyState !== SOCKET_OPEN) return;
		this.socket.send(
			JSON.stringify({
				protocolVersion: 1,
				type,
				resourceId,
				subscriptionId,
				payload: {},
			}),
		);
	}

	private sendBinary(
		resourceId: string,
		messageType: SyncMessageType,
		payload: Uint8Array,
	): void {
		const subscription = this.subscriptions.get(resourceId);
		if (!subscription || this.socket?.readyState !== SOCKET_OPEN) return;
		this.socket.send(
			encodeRealtimeBinaryFrame(
				{
					messageType,
					resourceId,
					subscriptionId: subscription.subscriptionId,
				},
				payload,
			),
		);
	}

	private scheduleReconnect(): void {
		if (this.manuallyClosed || this.reconnectTimer) return;
		const delay = Math.min(this.retryDelay, 20_000);
		this.retryDelay = Math.min(this.retryDelay * 2, 20_000);
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			this.open();
		}, delay);
	}

	private setConnectionState(state: RealtimeConnectionState): void {
		this.connectionState = state;
		for (const listener of this.stateListeners) listener(state);
		for (const subscription of this.subscriptions.values()) {
			subscription.handlers.onStatus(state);
		}
	}
}

export function createResourceRealtimeClient(
	url: string,
	socketFactory?: RealtimeSocketFactory,
): ResourceRealtimeClient {
	return new ManagedResourceRealtimeClient(url, socketFactory);
}
