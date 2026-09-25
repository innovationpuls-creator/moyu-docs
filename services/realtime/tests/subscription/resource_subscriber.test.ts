import { describe, expect, it, vi } from "vitest";
import { MemoryPresenceStore } from "../../src/backlog/presence_store.js";
import { MemoryYjsBacklogStore } from "../../src/backlog/yjs_backlog_store.js";
import type { AwarenessEvent } from "../../src/protocol/realtime_frame.js";
import { ResourceSubscriptionManager } from "../../src/subscription/resource_subscriber.js";

class FakeAuthorizer {
	allowed = new Set<string>();
	editable = new Set<string>();
	updateChecks: string[] = [];

	async authorizeResource(
		actorId: string,
		resourceId: string,
	): Promise<boolean> {
		return this.allowed.has(`${actorId}:${resourceId}`);
	}

	async authorizeResourceUpdate(
		actorId: string,
		resourceId: string,
	): Promise<boolean> {
		this.updateChecks.push(`${actorId}:${resourceId}`);
		return this.editable.has(`${actorId}:${resourceId}`);
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
		const { authorizer, manager } = setup();
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

it("persists roster membership across joins and drops", async () => {
	const authorizer = new FakeAuthorizer();
	const sent: Array<{ to: string; envelope: unknown }> = [];
	const presence = new MemoryPresenceStore();
	const manager = new ResourceSubscriptionManager(
		authorizer,
		{ send: (to, envelope) => sent.push({ to, envelope }) },
		undefined,
		presence,
	);
	authorizer.allowed.add("actor-a:res-1");
	authorizer.allowed.add("actor-b:res-1");
	await manager.subscribe("c1", "actor-a", "res-1");
	await manager.subscribe("c2", "actor-b", "res-1");
	expect((await presence.peers("res-1")).sort()).toEqual([
		"actor-a",
		"actor-b",
	]);
	manager.dropConnection("c1");
	expect(await presence.peers("res-1")).toEqual(["actor-b"]);
});

it("keeps read subscriptions live but gates every Yjs update before backlog and fan-out", async () => {
	const authorizer = new FakeAuthorizer();
	const sent: Array<{ to: string; envelope: unknown }> = [];
	const backlog = new MemoryYjsBacklogStore();
	const manager = new ResourceSubscriptionManager(
		authorizer,
		{ send: (to, envelope) => sent.push({ to, envelope }) },
		backlog,
	);
	authorizer.allowed.add("session-reader:res-1");
	authorizer.allowed.add("session-editor:res-1");
	await manager.subscribe(
		"reader-connection",
		"session-reader",
		"res-1",
		"sub-reader",
	);
	await manager.subscribe(
		"editor-connection",
		"session-editor",
		"res-1",
		"sub-editor",
	);
	sent.length = 0;

	expect(
		await manager.publishYjsUpdate(
			"reader-connection",
			"res-1",
			"sub-reader",
			"cmVhZGVyLXVwZGF0ZQ==",
		),
	).toBe(false);
	expect(await backlog.recent("res-1")).toEqual([]);
	expect(sent.filter((item) => item.to === "editor-connection")).toEqual([]);
	expect(manager.isSubscribed("reader-connection", "res-1", "sub-reader")).toBe(
		true,
	);

	authorizer.editable.add("session-reader:res-1");
	expect(
		await manager.publishYjsUpdate(
			"reader-connection",
			"res-1",
			"sub-reader",
			"cmVhZGVyLW5leHQ=",
		),
	).toBe(true);
	expect(authorizer.updateChecks).toEqual([
		"session-reader:res-1",
		"session-reader:res-1",
	]);
	expect(await backlog.recent("res-1")).toEqual(["cmVhZGVyLW5leHQ="]);
	expect(
		sent.some(
			(item) =>
				item.to === "editor-connection" &&
				(item.envelope as { payload?: { kind?: string } }).payload?.kind ===
					"yjs",
		),
	).toBe(true);
});

it("publishes authorized cursor state, snapshots peers, throttles, and cleans each tab independently", async () => {
	vi.useFakeTimers();
	try {
		const { authorizer, manager, sent } = setup();
		authorizer.allowed.add("session-a:res-1");
		authorizer.allowed.add("session-b:res-1");
		await manager.subscribe("c1", "session-a", "res-1", "sub-a", {
			accountId: "account-same",
		});
		await manager.subscribe("c2", "session-b", "res-1", "sub-b", {
			accountId: "account-same",
		});

		const awarenessMessages = (to: string) =>
			sent
				.filter(
					(item) =>
						item.to === to &&
						(item.envelope as { payload?: { kind?: string } }).payload?.kind ===
							"awareness",
				)
				.map(
					(item) =>
						(item.envelope as { payload: { event: AwarenessEvent } }).payload
							.event,
				);
		const snapshot = awarenessMessages("c2").find(
			(event) => event.kind === "update",
		);
		expect(snapshot).toMatchObject({
			kind: "update",
			participant: {
				displayName: "协作者-SAME",
				color: expect.stringMatching(/^#[0-9a-f]{6}$/),
			},
		});
		if (snapshot?.kind !== "update")
			throw new Error("expected awareness snapshot");
		const tabAParticipantId = snapshot.participant.participantId;
		const tabBEvent = awarenessMessages("c1").find(
			(event) => event.kind === "update",
		);
		if (tabBEvent?.kind !== "update")
			throw new Error("expected second tab presence");
		expect(tabBEvent.participant.participantId).not.toBe(tabAParticipantId);
		const tabBParticipantId = tabBEvent.participant.participantId;

		const forgedState = {
			actorId: "some-other-user",
			cursor: { anchor: 1, head: 2 },
		};
		expect(manager.publishAwareness("c1", "res-1", "sub-a", forgedState)).toBe(
			false,
		);
		expect(
			manager.publishAwareness("c1", "res-1", "stale-sub", { cursor: null }),
		).toBe(false);
		expect(
			manager.publishAwareness("c1", "res-1", "sub-a", {
				cursor: { anchor: 4, head: 6 },
			}),
		).toBe(true);
		manager.publishAwareness("c1", "res-1", "sub-a", {
			cursor: { anchor: 8, head: 10 },
		});
		manager.publishAwareness("c1", "res-1", "sub-a", {
			cursor: { anchor: 11, head: 13 },
		});
		await vi.advanceTimersByTimeAsync(80);
		const latest = awarenessMessages("c2").filter(
			(event) =>
				event.kind === "update" &&
				event.participant.participantId === tabAParticipantId,
		);
		expect(latest.at(-1)).toMatchObject({
			state: { cursor: { anchor: 11, head: 13 } },
		});
		authorizer.allowed.add("session-c:res-1");
		await manager.subscribe("c3", "session-c", "res-1", "sub-c", {
			accountId: "account-third",
		});
		expect(
			awarenessMessages("c3").find(
				(event) =>
					event.kind === "update" &&
					event.participant.participantId === tabAParticipantId,
			),
		).toMatchObject({ state: { cursor: { anchor: 11, head: 13 } } });

		manager.unsubscribe("c1", "res-1", "sub-a");
		expect(awarenessMessages("c2").at(-1)).toEqual({
			kind: "remove",
			participantId: tabAParticipantId,
		});
		expect(awarenessMessages("c3").at(-1)).toEqual({
			kind: "remove",
			participantId: tabAParticipantId,
		});
		expect(manager.isSubscribed("c2", "res-1", "sub-b")).toBe(true);
		expect(
			manager.publishAwareness("c2", "res-1", "sub-b", { cursor: null }),
		).toBe(true);
		manager.publishAwareness("c2", "res-1", "sub-b", {
			cursor: { anchor: 2, head: 2 },
		});
		manager.dropConnection("c2");
		await vi.advanceTimersByTimeAsync(80);
		expect(awarenessMessages("c3").at(-1)).toEqual({
			kind: "remove",
			participantId: tabBParticipantId,
		});
	} finally {
		vi.useRealTimers();
	}
});
