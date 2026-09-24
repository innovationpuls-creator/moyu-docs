import { connect } from "nats";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GatewayRelayHost } from "../../src/relay/gateway_relay_host.js";

const NATS_URL = "nats://localhost:4222";

describe("GatewayRelayHost", () => {
	let nc: Awaited<ReturnType<typeof connect>>;
	let host: GatewayRelayHost;

	beforeEach(async () => {
		nc = await connect({ servers: NATS_URL });
		host = new GatewayRelayHost({
			apiBaseUrl: "http://127.0.0.1:1",
			natsUrl: NATS_URL,
		});
		await host.startRelay();
	});

	afterEach(async () => {
		await host.stopRelay();
		await nc.close();
	});

	it("dispatches published broadcasts only to the subscribed connection", async () => {
		const outboxA: unknown[] = [];
		const outboxB: unknown[] = [];
		await host.registerConnection("conn-a", (envelope) =>
			outboxA.push(envelope),
		);
		await host.registerConnection("conn-b", (envelope) =>
			outboxB.push(envelope),
		);
		// Authorization is API-driven and denied in this offline harness; the
		// subject routing itself is exercised directly like the gateway would
		// after a successful authorize.
		host.manager["subscriptions"].set("conn-a", new Set(["rt.resource.res-1"]));
		host.manager["bySubject"].set("rt.resource.res-1", new Set(["conn-a"]));
		await nc.publish(
			"rt.broadcast.res-1",
			JSON.stringify({
				resourceId: "res-1",
				kind: "op",
				payload: { journalSeq: 3 },
				sequence: 3,
			}),
		);
		const deadline = Date.now() + 5000;
		while (outboxA.length === 0 && Date.now() < deadline) {
			await new Promise((resolve) => setTimeout(resolve, 50));
		}
		expect(outboxA).toHaveLength(1);
		const routed = outboxA[0] as {
			kind: string;
			payload: { journalSeq: number };
		};
		expect(routed.kind).toBe("op");
		expect(routed.payload.journalSeq).toBe(3);
		expect(outboxB).toHaveLength(0); // B never subscribed to res-1
	});
});
