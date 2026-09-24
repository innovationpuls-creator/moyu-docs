import { describe, expect, it } from "vitest";

import { MemoryYjsBacklogStore } from "../../src/backlog/yjs_backlog_store.js";
import { ResourceSubscriptionManager } from "../../src/subscription/resource_subscriber.js";

class FakeAuthorizer {
	allowed = new Set<string>();

	async authorizeResource(
		actorId: string,
		resourceId: string,
	): Promise<boolean> {
		return this.allowed.has(`${actorId}:${resourceId}`);
	}
}

function setup() {
	const authorizer = new FakeAuthorizer();
	const sent: Array<{ to: string; envelope: unknown }> = [];
	const manager = new ResourceSubscriptionManager(authorizer, {
		send: (to, envelope) => sent.push({ to, envelope }),
	});
	return { authorizer, manager, sent };
}

describe("ResourceSubscriptionManager", () => {
	it("rejects a subscription the authorizer denies", async () => {
		const { manager, sent } = setup();
		const result = await manager.subscribe("c1", "actor-a", "res-1");
		expect(result).toBe("denied");
		expect(sent).toHaveLength(0);
	});

	it("accepts an owned subscription and routes dispatch to that subject only", async () => {
		const { authorizer, manager, sent } = setup();
		authorizer.allowed.add("actor-a:res-1");
		authorizer.allowed.add("actor-b:res-2");
		await manager.subscribe("c1", "actor-a", "res-1");
		await manager.subscribe("c2", "actor-b", "res-2");
		const toSubscribers = manager.dispatch("res-1", {
			kind: "op",
			payload: { seq: 1 },
		});
		expect(toSubscribers).toBe(1);
		const opMessages = sent.filter(
			(m) =>
				(m.envelope as { kind?: string }).kind === "op" &&
				(m.envelope as { payload?: { kind?: string } }).payload?.kind !==
					"roster",
		);
		expect(opMessages).toHaveLength(1);
		expect(opMessages[0].to).toBe("c1");
	});

	it("stops delivery after unsubscribe and cleans up on drop", async () => {
		const { authorizer, manager, sent } = setup();
		authorizer.allowed.add("actor-a:res-1");
		await manager.subscribe("c1", "actor-a", "res-1");
		manager.unsubscribe("c1", "res-1");
		expect(manager.dispatch("res-1", { kind: "op", payload: {} })).toBe(0);
		manager.dropConnection("c1");
		expect(manager.dispatch("res-1", { kind: "op", payload: {} })).toBe(0);
	});
});

it("broadcasts a roster count on join and leave", async () => {
	const { authorizer, manager, sent } = setup();
	authorizer.allowed.add("actor-a:res-1");
	authorizer.allowed.add("actor-b:res-1");
	await manager.subscribe("c1", "actor-a", "res-1");
	await manager.subscribe("c2", "actor-b", "res-1");
	const rosterMessages = sent.filter(
		(m) =>
			(m.envelope as { payload?: { kind?: string } }).payload?.kind ===
			"roster",
	);
	expect(rosterMessages.length).toBeGreaterThanOrEqual(2);
	const afterJoin = rosterMessages[rosterMessages.length - 1];
	expect(
		(afterJoin.envelope as { payload?: { peers?: number } }).payload?.peers,
	).toBe(2);
	manager.dropConnection("c2");
	const afterLeave = sent
		.filter(
			(m) =>
				(m.envelope as { payload?: { kind?: string } }).payload?.kind ===
				"roster",
		)
		.at(-1);
	expect(afterLeave).toBeDefined();
	const leaveEnvelope = afterLeave?.envelope as {
		payload?: { peers?: number };
	};
	expect(leaveEnvelope.payload?.peers).toBe(1);
});

it("replays the yjs backlog to a late joiner (catch-up)", async () => {
	const { authorizer, manager, sent } = setup();
	authorizer.allowed.add("actor-a:res-1");
	authorizer.allowed.add("actor-b:res-1");
	await manager.subscribe("c1", "actor-a", "res-1");
	manager.recordYjsUpdate("res-1", "dXBkYXRlMQ==");
	manager.recordYjsUpdate("res-1", "dXBkYXRlMg==");
	sent.length = 0; // only c2's catch-up counts from here
	await manager.subscribe("c2", "actor-b", "res-1");
	const backlogToC2 = sent.filter(
		(m) =>
			m.to === "c2" &&
			(m.envelope as { payload?: { kind?: string } }).payload?.kind === "yjs",
	);
	expect(backlogToC2).toHaveLength(2);
	const first = backlogToC2[0].envelope as {
		payload?: { update?: string };
	};
	expect(first.payload?.update).toBe("dXBkYXRlMQ==");
});

it("bounds the backlog and drops the oldest updates", async () => {
	const { authorizer, manager, sent } = setup();
	authorizer.allowed.add("actor-a:res-1");
	authorizer.allowed.add("actor-b:res-1");
	await manager.subscribe("c1", "actor-a", "res-1");
	for (let i = 0; i < 60; i += 1) {
		manager.recordYjsUpdate("res-1", `u${i}`);
	}
	sent.length = 0;
	await manager.subscribe("c2", "actor-b", "res-1");
	const backlogToC2 = sent.filter(
		(m) =>
			m.to === "c2" &&
			(m.envelope as { payload?: { kind?: string } }).payload?.kind === "yjs",
	);
	expect(backlogToC2).toHaveLength(50);
	const first = backlogToC2[0].envelope as {
		payload?: { update?: string };
	};
	expect(first.payload?.update).toBe("u10");
});

it("incrementalSync replays the missing tail for a stale vector", async () => {
	const authorizer = new FakeAuthorizer();
	const sent: Array<{ to: string; envelope: unknown }> = [];
	const store = new MemoryYjsBacklogStore();
	const manager = new ResourceSubscriptionManager(
		authorizer,
		{ send: (to, envelope) => sent.push({ to, envelope }) },
		store,
	);
	authorizer.allowed.add("actor-a:res-1");
	await manager.subscribe("c1", "actor-a", "res-1");
	const Y = await import("yjs");
	const doc = new Y.Doc();
	const text = doc.getText("content");
	doc.transact(() => {
		text.insert(0, "标题");
	});
	const firstUpdate = Y.encodeStateAsUpdate(doc);
	await store.record("res-1", btoa(String.fromCharCode(...firstUpdate)));
	const staleVector = Y.encodeStateVector(doc);
	doc.transact(() => {
		text.insert(3, " 追加");
	});
	const secondUpdate = Y.encodeStateAsUpdate(doc);
	await store.record("res-1", btoa(String.fromCharCode(...secondUpdate)));
	sent.length = 0;
	await manager.incrementalSync(
		"c2",
		"res-1",
		btoa(String.fromCharCode(...staleVector)),
	);
	const syncOps = sent.filter(
		(m) =>
			m.to === "c2" &&
			(m.envelope as { payload?: { kind?: string } }).payload?.kind === "yjs",
	);
	expect(syncOps).toHaveLength(1);
	const update = (syncOps[0].envelope as { payload?: { update?: string } })
		.payload?.update as string;
	// the tail must be NON-EMPTY: the stale replica needs the second delta
	expect(update.length).toBeGreaterThan(0);
	// sync contract: a replica at `staleVector`, replayed the tail, converges
	const replica = new Y.Doc();
	Y.applyUpdate(replica, Uint8Array.from(firstUpdate));
	Y.applyUpdate(
		replica,
		Uint8Array.from(atob(update), (c) => c.charCodeAt(0)),
	);
	expect(replica.getText("content").toString()).toBe("标题 追加");
});
