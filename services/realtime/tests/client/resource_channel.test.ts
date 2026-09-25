import { describe, expect, it, vi } from "vitest";
import {
	ManagedResourceRealtimeClient,
	type ResourceRealtimeHandlers,
} from "../../../../packages/ts/realtime-client/src/index.js";
import {
	decodeRealtimeBinaryFrame,
	encodeRealtimeBinaryFrame,
} from "../../../../packages/ts/realtime-protocol/src/index.js";

type Listener = (event: never) => void;

class FakeSocket {
	readyState = 0;
	sent: Array<string | Uint8Array> = [];
	closed = false;
	private readonly listeners = new Map<string, Listener[]>();

	addEventListener(type: string, listener: Listener): void {
		const handlers = this.listeners.get(type) ?? [];
		handlers.push(listener);
		this.listeners.set(type, handlers);
	}

	send(data: string | Uint8Array): void {
		this.sent.push(data);
	}

	close(code = 1000, reason = ""): void {
		this.closed = true;
		this.readyState = 3;
		this.emit("close", { code, reason });
	}

	open(): void {
		this.readyState = 1;
		this.emit("open", {});
	}

	receive(data: string | Uint8Array): void {
		this.emit("message", { data });
	}

	private emit(type: string, event: unknown): void {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event as never);
		}
	}
}

function handlers(overrides: Partial<ResourceRealtimeHandlers> = {}) {
	return {
		getStateVector: () => new Uint8Array([1]),
		getLocalState: () => new Uint8Array([2]),
		onUpdate: vi.fn(),
		onPeers: vi.fn(),
		onStatus: vi.fn(),
		...overrides,
	} satisfies ResourceRealtimeHandlers;
}

function sentControl(
	socket: FakeSocket,
	index: number,
): Record<string, unknown> {
	const data = socket.sent[index];
	if (typeof data !== "string") throw new Error("expected a control frame");
	return JSON.parse(data) as Record<string, unknown>;
}

describe("ManagedResourceRealtimeClient", () => {
	it("sends binary sync frames, receives updates and reconnects subscriptions", async () => {
		vi.useFakeTimers();
		const sockets: FakeSocket[] = [];
		const client = new ManagedResourceRealtimeClient("ws://gateway", () => {
			const socket = new FakeSocket();
			sockets.push(socket);
			return socket;
		});
		const callbacks = handlers();
		const unsubscribe = client.subscribeResource("resource-1", callbacks);
		const first = sockets[0];
		first.open();
		const subscribe = sentControl(first, 0);
		first.receive(
			JSON.stringify({
				protocolVersion: 1,
				resourceId: "resource-1",
				kind: "subscribe",
				payload: { status: "ok" },
			}),
		);
		const stateVector = first.sent[1];
		const localState = first.sent[2];
		expect(stateVector).toBeInstanceOf(Uint8Array);
		expect(localState).toBeInstanceOf(Uint8Array);
		expect(
			decodeRealtimeBinaryFrame(stateVector as Uint8Array).header.messageType,
		).toBe("sync.state-vector");
		expect(
			decodeRealtimeBinaryFrame(localState as Uint8Array).header.messageType,
		).toBe("sync.update");
		const update = encodeRealtimeBinaryFrame(
			{
				messageType: "sync.update",
				resourceId: "resource-1",
				subscriptionId: String(subscribe.subscriptionId),
			},
			new Uint8Array([9, 8]),
		);
		first.receive(update);
		expect(callbacks.onUpdate).toHaveBeenCalledWith(new Uint8Array([9, 8]));
		first.receive(
			JSON.stringify({
				protocolVersion: 1,
				resourceId: "resource-1",
				kind: "op",
				payload: { kind: "roster", peers: 3 },
			}),
		);
		expect(callbacks.onPeers).toHaveBeenCalledWith(3);

		first.close(1006, "network lost");
		await vi.advanceTimersByTimeAsync(500);
		const second = sockets[1];
		expect(second).toBeDefined();
		second.open();
		expect(sentControl(second, 0).type).toBe("subscribe");
		client.close();
		unsubscribe();
		vi.useRealTimers();
	});

	it("surfaces a replaced session without reconnecting", () => {
		const sockets: FakeSocket[] = [];
		const client = new ManagedResourceRealtimeClient("ws://gateway", () => {
			const socket = new FakeSocket();
			sockets.push(socket);
			return socket;
		});
		const replaced = vi.fn();
		client.onSessionReplaced(replaced);
		sockets[0].receive(
			JSON.stringify({
				type: "SessionReplaced",
				reason: "NewDeviceLogin",
				message: "本设备已下线",
			}),
		);
		sockets[0].close(4001, "session replaced");
		expect(replaced).toHaveBeenCalledWith(
			expect.objectContaining({ closeCode: 4001, reason: "NewDeviceLogin" }),
		);
		client.close();
	});
});
