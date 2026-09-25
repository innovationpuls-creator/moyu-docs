import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import type { WebSocket } from "ws";
import type { GatewayRelayHost } from "../../src/relay/gateway_relay_host.js";
import {
	createShareBootstrapQueue,
	registerPublicShareConnection,
} from "../../src/server/websocket_server.js";

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

function fakeSocket() {
	const socket = new EventEmitter() as EventEmitter & {
		readyState: number;
		OPEN: number;
		send: ReturnType<typeof vi.fn>;
		close: ReturnType<typeof vi.fn>;
	};
	socket.readyState = 1;
	socket.OPEN = 1;
	socket.send = vi.fn();
	socket.close = vi.fn((..._args: unknown[]) => {
		socket.readyState = 3;
		socket.emit("close");
	});
	return socket;
}

describe("public share bootstrap", () => {
	it("subscribes before reading current state and flushes buffered updates after it", async () => {
		const socket = fakeSocket();
		const state = deferred<Uint8Array | null>();
		const stateReadStarted = deferred<void>();
		const events: string[] = [];
		let subscribed = false;
		const bootstrapQueue = createShareBootstrapQueue((envelope) =>
			events.push(String(envelope)),
		);
		const manager = {
			subscribePublicShare: vi.fn(() => {
				subscribed = true;
				events.push("subscribed");
				bootstrapQueue.enqueue("live-update-during-bootstrap");
			}),
			sendPublicShareState: vi.fn(() => events.push("current-state")),
		};
		const relayHost = {
			resolvePublicShare: vi.fn(async () => ({
				resourceId: "resource-1",
				journalSeq: 4,
			})),
			readCurrentPublicState: vi.fn(() => {
				expect(subscribed).toBe(true);
				events.push("state-query");
				stateReadStarted.resolve();
				return state.promise;
			}),
			manager,
		} as unknown as GatewayRelayHost;
		let bootstrapFinished = false;
		const finishBootstrap = vi.fn(() => {
			events.push("bootstrap-finished");
			bootstrapQueue.finish();
			bootstrapFinished = true;
		});

		registerPublicShareConnection(
			socket as unknown as WebSocket,
			"share-connection",
			relayHost,
			finishBootstrap,
			60_000,
		);
		socket.emit(
			"message",
			Buffer.from(
				JSON.stringify({
					protocolVersion: 1,
					type: "authenticate-share",
					token: "test-share-token",
				}),
			),
			false,
		);
		await vi.waitFor(() =>
			expect(relayHost.resolvePublicShare).toHaveBeenCalledTimes(1),
		);

		socket.emit(
			"message",
			Buffer.from(
				JSON.stringify({
					protocolVersion: 1,
					type: "subscribe",
					resourceId: "resource-1",
					subscriptionId: "subscription-1",
				}),
			),
			false,
		);
		await stateReadStarted.promise;

		expect(events).toEqual(["subscribed", "state-query"]);
		expect(bootstrapFinished).toBe(false);
		state.resolve(Uint8Array.of(1, 2, 3));
		await vi.waitFor(() => expect(bootstrapFinished).toBe(true));

		expect(manager.sendPublicShareState).toHaveBeenCalledWith(
			"share-connection",
			"resource-1",
			"subscription-1",
			Buffer.from([1, 2, 3]).toString("base64"),
		);
		expect(events).toEqual([
			"subscribed",
			"state-query",
			"current-state",
			"bootstrap-finished",
			"live-update-during-bootstrap",
		]);
		const sent = socket.send.mock.calls.map(([message]: unknown[]) =>
			JSON.parse(String(message)),
		);
		expect(sent.map((message: { type?: string }) => message.type)).toEqual([
			"share-authenticated",
			"share-state",
		]);

		socket.close(1000, "test complete");
	});
});
