import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoryYjsBacklogStore } from "../../src/backlog/yjs_backlog_store.js";
import { GatewayRelayHost } from "../../src/relay/gateway_relay_host.js";

const API_BASE = "http://api.test";
const RESOURCE_ID = "resource-1";

function response(body: string, status = 200): Response {
	return new Response(body, { status });
}

describe("GatewayRelayHost update authorization", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("rechecks capabilities on every update and denies after a downgrade", async () => {
		let canUpdate = true;
		const calls: Array<{ url: string; cookie: string | null }> = [];
		const fetchMock = vi.fn(
			async (input: RequestInfo | URL, init?: RequestInit) => {
				const url = String(input);
				const cookie = new Headers(init?.headers).get("cookie");
				calls.push({ url, cookie });
				if (url.endsWith("/capabilities")) {
					return response(
						JSON.stringify({ resourceId: RESOURCE_ID, canUpdate }),
					);
				}
				return response("{}");
			},
		);
		vi.stubGlobal("fetch", fetchMock);

		const backlog = new MemoryYjsBacklogStore();
		const host = new GatewayRelayHost({
			apiBaseUrl: API_BASE,
			natsUrl: "nats://unused",
			backlogStore: backlog,
		});
		const delivered: unknown[] = [];
		await host.registerConnection("writer", (message) =>
			delivered.push(message),
		);
		await host.registerConnection("reader", (message) =>
			delivered.push(message),
		);
		await host.manager.subscribe(
			"writer",
			"writer-session",
			RESOURCE_ID,
			"sub-w",
		);
		await host.manager.subscribe(
			"reader",
			"reader-session",
			RESOURCE_ID,
			"sub-r",
		);
		delivered.length = 0;

		expect(
			await host.manager.publishYjsUpdate(
				"writer",
				RESOURCE_ID,
				"sub-w",
				"d3JpdGUtMQ==",
			),
		).toBe(true);
		canUpdate = false;
		expect(
			await host.manager.publishYjsUpdate(
				"writer",
				RESOURCE_ID,
				"sub-w",
				"d3JpdGUtMg==",
			),
		).toBe(false);

		const capabilityCalls = calls.filter((call) =>
			call.url.endsWith("/capabilities"),
		);
		expect(capabilityCalls).toEqual([
			{
				url: `${API_BASE}/v1/resources/${RESOURCE_ID}/capabilities`,
				cookie: "dom_session=writer-session",
			},
			{
				url: `${API_BASE}/v1/resources/${RESOURCE_ID}/capabilities`,
				cookie: "dom_session=writer-session",
			},
		]);
		expect(await backlog.recent(RESOURCE_ID)).toEqual(["d3JpdGUtMQ=="]);
		expect(delivered).toHaveLength(1);
		expect(
			(delivered[0] as { payload?: { update?: string } }).payload?.update,
		).toBe("d3JpdGUtMQ==");
	});

	it.each([
		{
			name: "non-200 response",
			capability: () => response("{}", 403),
		},
		{
			name: "wrong resource identity",
			capability: () =>
				response(JSON.stringify({ resourceId: "other", canUpdate: true })),
		},
		{
			name: "missing write capability",
			capability: () => response(JSON.stringify({ resourceId: RESOURCE_ID })),
		},
		{
			name: "malformed response",
			capability: () => response("{"),
		},
		{
			name: "network error",
			capability: () => Promise.reject(new Error("offline")),
		},
	])("fails closed for $name", async ({ capability }) => {
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			if (String(input).endsWith("/capabilities")) return capability();
			return response("{}");
		});
		vi.stubGlobal("fetch", fetchMock);
		const backlog = new MemoryYjsBacklogStore();
		const host = new GatewayRelayHost({
			apiBaseUrl: API_BASE,
			natsUrl: "nats://unused",
			backlogStore: backlog,
		});
		const delivered: unknown[] = [];
		await host.registerConnection("writer", (message) =>
			delivered.push(message),
		);
		await host.manager.subscribe(
			"writer",
			"writer-session",
			RESOURCE_ID,
			"sub-w",
		);
		delivered.length = 0;

		expect(
			await host.manager.publishYjsUpdate(
				"writer",
				RESOURCE_ID,
				"sub-w",
				"d3JpdGUtMQ==",
			),
		).toBe(false);
		expect(await backlog.recent(RESOURCE_ID)).toEqual([]);
		expect(delivered).toEqual([]);
	});
});
