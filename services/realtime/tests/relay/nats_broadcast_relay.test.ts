import type { Msg } from "nats";
import { describe, expect, it } from "vitest";
import { NatsBroadcastRelay } from "../../src/relay/nats_broadcast_relay.js";

function fakeMsg(data: Buffer, bucket: { acked: number; termed: number }): Msg {
	return {
		data,
		ack: () => {
			bucket.acked += 1;
			return Promise.resolve(undefined);
		},
		term: () => {
			bucket.termed += 1;
			return Promise.resolve(undefined);
		},
	} as unknown as Msg;
}

describe("NatsBroadcastRelay", () => {
	it("dispatches a well-formed broadcast envelope to the sink and acks", async () => {
		const bucket = { acked: 0, termed: 0 };
		const dispatched: Array<{ resourceId: string; envelope: unknown }> = [];
		const messages: Msg[] = [
			fakeMsg(
				Buffer.from(
					JSON.stringify({
						resourceId: "res-1",
						kind: "op",
						payload: { seq: 1 },
					}),
				),
				bucket,
			),
		];
		const relay = new NatsBroadcastRelay({} as never, {
			dispatch: (resourceId, envelope) => {
				dispatched.push({ resourceId, envelope });
				return 1;
			},
		});
		const iterator = (async function* () {
			for (const m of messages) yield m;
		})();
		relay["sub"] = { [Symbol.asyncIterator]: () => iterator } as never;
		await relay["consume"]();
		expect(dispatched).toHaveLength(1);
		expect(dispatched[0].resourceId).toBe("res-1");
		expect(bucket.acked).toBe(1);
		expect(bucket.termed).toBe(0);
	});

	it("terms malformed envelopes", async () => {
		const bucket = { acked: 0, termed: 0 };
		const messages: Msg[] = [
			fakeMsg(Buffer.from("{not json"), bucket),
			fakeMsg(Buffer.from(JSON.stringify({ kind: "op" })), bucket),
		];
		const relay = new NatsBroadcastRelay({} as never, {
			dispatch: () => 0,
		});
		const iterator = (async function* () {
			for (const m of messages) yield m;
		})();
		relay["sub"] = { [Symbol.asyncIterator]: () => iterator } as never;
		await relay["consume"]();
		expect(bucket.termed).toBe(2);
		expect(bucket.acked).toBe(0);
	});
});
