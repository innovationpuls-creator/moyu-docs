import { describe, expect, it, vi } from "vitest";

import {
	ResourceChannelClient,
	type ResourceChannelMessage,
} from "../../../../packages/ts/realtime-client/src/index.js";

class FakeSocket {
	sent: string[] = [];
	onmessage: ((event: { data: string }) => void) | null = null;
	closed = false;

	send(data: string): void {
		this.sent.push(data);
	}

	close(): void {
		this.closed = true;
	}

	receive(message: ResourceChannelMessage): void {
		this.onmessage?.({ data: JSON.stringify(message) });
	}
}

describe("ResourceChannelClient", () => {
	it("sends a subscribe envelope and routes ops to the resource handler", () => {
		const socket = new FakeSocket();
		const client = new ResourceChannelClient(socket);
		client.attach();
		const handler = vi.fn();
		client.onResource("res-1", handler);
		client.subscribe("res-1");
		socket.receive({
			type: "op",
			resourceId: "res-1",
			payload: { seq: 3 },
			sequence: 3,
		});
		expect(socket.sent[0]).toContain('"type":"subscribe"');
		expect(handler).toHaveBeenCalledTimes(1);
		const routed = handler.mock.calls[0][0] as ResourceChannelMessage;
		expect(routed.payload).toEqual({ seq: 3 });
	});

	it("routes presence to the any-handler and closes the socket", () => {
		const socket = new FakeSocket();
		const client = new ResourceChannelClient(socket);
		client.attach();
		const anyHandler = vi.fn();
		client.onAny(anyHandler);
		client.subscribe("res-1");
		socket.receive({
			type: "presence",
			resourceId: "res-1",
			payload: { actorId: "a", kind: "join" },
		});
		expect(anyHandler).toHaveBeenCalledTimes(1);
		client.close();
		expect(socket.closed).toBe(true);
	});
});
