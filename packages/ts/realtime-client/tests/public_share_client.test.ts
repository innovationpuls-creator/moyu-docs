import { describe, expect, it } from "vitest";
import {
	createPublicShareRealtimeClient,
	createResourceRealtimeClient,
	type ResourceRealtimeHandlers,
} from "../src/index.js";
import {
	decodeRealtimeBinaryFrame,
	encodeRealtimeBinaryFrame,
} from "../src/realtime_protocol.js";

class FakeSocket {
	readyState = 0;
	readonly sent: Array<string | Uint8Array> = [];
	readonly listeners = new Map<string, Array<(event: never) => void>>();
	closeCode: number | undefined;

	addEventListener(type: string, listener: (event: never) => void): void {
		const listeners = this.listeners.get(type) ?? [];
		listeners.push(listener);
		this.listeners.set(type, listeners);
	}

	send(data: string | Uint8Array): void {
		this.sent.push(data);
	}

	close(code?: number): void {
		this.closeCode = code;
		this.readyState = 3;
	}

	open(): void {
		this.readyState = 1;
		this.emit("open", {});
	}

	message(data: string | Uint8Array): void {
		this.emit("message", { data });
	}

	private emit(type: string, event: object): void {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event as never);
		}
	}
}

function publicHandlers(
	options: Partial<ResourceRealtimeHandlers> = {},
): ResourceRealtimeHandlers {
	return {
		getStateVector: () => new Uint8Array(),
		getLocalState: () => new Uint8Array(),
		onUpdate: () => {},
		onPeers: () => {},
		onStatus: () => {},
		...options,
	};
}

describe("public share realtime client", () => {
	it("authenticates before subscribing and never publishes member state", () => {
		const socket = new FakeSocket();
		const shareStates: string[] = [];
		const updates: number[][] = [];
		const client = createPublicShareRealtimeClient(
			"ws://localhost/realtime",
			"public-share-token",
			() => socket,
		);
		let stateVectorReads = 0;
		let localStateReads = 0;
		const unsubscribe = client.subscribeResource(
			"resource-1",
			publicHandlers({
				getStateVector: () => {
					stateVectorReads += 1;
					return Uint8Array.of(1);
				},
				getLocalState: () => {
					localStateReads += 1;
					return Uint8Array.of(2);
				},
				onUpdate: (update) => updates.push([...update]),
				onShareState: (kind) => shareStates.push(kind),
			}),
		);

		socket.open();
		expect(JSON.parse(String(socket.sent[0]))).toEqual({
			protocolVersion: 1,
			type: "authenticate-share",
			token: "public-share-token",
		});
		expect(socket.sent).toHaveLength(1);

		socket.message(
			JSON.stringify({
				protocolVersion: 1,
				type: "share-authenticated",
				payload: { status: "ok" },
			}),
		);
		const subscribe = JSON.parse(String(socket.sent[1])) as {
			type: string;
			resourceId: string;
			subscriptionId: string;
		};
		expect(subscribe).toMatchObject({
			type: "subscribe",
			resourceId: "resource-1",
		});
		expect(socket.sent).toHaveLength(2);

		socket.message(
			JSON.stringify({
				protocolVersion: 1,
				resourceId: "resource-1",
				subscriptionId: subscribe.subscriptionId,
				kind: "subscribe",
				payload: { status: "ok" },
			}),
		);
		client.publishUpdate("resource-1", Uint8Array.of(3));
		client.publishAwareness("resource-1", { cursor: null });
		client.requestStateVector("resource-1", Uint8Array.of(4));
		expect(socket.sent).toHaveLength(2);
		expect(stateVectorReads).toBe(0);
		expect(localStateReads).toBe(0);

		socket.message(
			JSON.stringify({
				protocolVersion: 1,
				type: "share-state",
				resourceId: "resource-1",
				subscriptionId: subscribe.subscriptionId,
				payload: { stateKind: "checkpoint" },
			}),
		);
		expect(shareStates).toEqual(["checkpoint"]);
		socket.message(
			JSON.stringify({
				protocolVersion: 1,
				type: "share-state",
				resourceId: "resource-1",
				subscriptionId: subscribe.subscriptionId,
				payload: { stateKind: "yjs" },
			}),
		);
		expect(shareStates).toEqual(["checkpoint", "yjs"]);
		socket.message(
			encodeRealtimeBinaryFrame(
				{
					messageType: "sync.update",
					resourceId: "resource-1",
					subscriptionId: subscribe.subscriptionId,
				},
				Uint8Array.of(8, 9),
			),
		);
		expect(updates).toEqual([[8, 9]]);

		unsubscribe();
		client.close();
	});

	it("preserves member subscribe handshake and initial state exchange", () => {
		const socket = new FakeSocket();
		const client = createResourceRealtimeClient(
			"ws://localhost/realtime",
			() => socket,
		);
		const unsubscribe = client.subscribeResource(
			"resource-1",
			publicHandlers({
				getStateVector: () => Uint8Array.of(1),
				getLocalState: () => Uint8Array.of(2),
			}),
		);
		socket.open();
		socket.message(
			JSON.stringify({
				protocolVersion: 1,
				resourceId: "resource-1",
				kind: "subscribe",
				payload: { status: "ok" },
			}),
		);

		const frames = socket.sent.filter(
			(value): value is Uint8Array => value instanceof Uint8Array,
		);
		expect(
			frames.map(
				(frame) => decodeRealtimeBinaryFrame(frame).header.messageType,
			),
		).toEqual(["sync.state-vector", "sync.update"]);
		expect(
			socket.sent.filter((value) => typeof value === "string"),
		).toHaveLength(2);

		unsubscribe();
		client.close();
	});
});
