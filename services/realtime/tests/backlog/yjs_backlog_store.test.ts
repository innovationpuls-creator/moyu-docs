import { describe, expect, it } from "vitest";

import {
	MemoryYjsBacklogStore,
	ValkeyYjsBacklogStore,
} from "../../src/backlog/yjs_backlog_store.js";

class FakeValkey {
	entries = new Map<string, string[]>();

	async rpush(key: string, ...values: string[]): Promise<number> {
		const list = this.entries.get(key) ?? [];
		list.push(...values);
		this.entries.set(key, list);
		return list.length;
	}

	async lrange(key: string, start: number, stop: number): Promise<string[]> {
		const list = this.entries.get(key) ?? [];
		const resolvedStart = start < 0 ? Math.max(0, list.length + start) : start;
		const resolvedEnd =
			stop < 0 ? list.length + stop + 1 : Math.min(list.length, stop + 1);
		return list.slice(resolvedStart, Math.max(0, resolvedEnd));
	}

	async ltrim(key: string, start: number, stop: number): Promise<"OK"> {
		const list = this.entries.get(key) ?? [];
		const resolvedStart = start < 0 ? Math.max(0, list.length + start) : start;
		const resolvedEnd =
			stop < 0 ? list.length + stop + 1 : Math.min(list.length, stop + 1);
		this.entries.set(key, list.slice(resolvedStart, Math.max(0, resolvedEnd)));
		return "OK";
	}

	expires = new Map<string, number>();

	async expire(key: string, seconds: number): Promise<number> {
		this.expires.set(key, seconds);
		return 1;
	}
}

describe("yjs backlog stores", () => {
	it("memory store records and returns bounded recent updates", async () => {
		const store = new MemoryYjsBacklogStore();
		for (let i = 0; i < 60; i += 1) {
			await store.record("res-1", `u${i}`);
		}
		const recent = await store.recent("res-1");
		expect(recent).toHaveLength(50);
		expect(recent[0]).toBe("u10");
	});

	it("valkey store round-trips through a fake redis list", async () => {
		const valkey = new FakeValkey();
		const store = new ValkeyYjsBacklogStore(valkey);
		await store.record("res-1", "one");
		await store.record("res-1", "two");
		await store.record("res-1", "three");
		const recent = await store.recent("res-1");
		expect(recent).toEqual(["one", "two", "three"]);
	});

	it("valkey store refreshes the key TTL on activity", async () => {
		const valkey = new FakeValkey();
		const store = new ValkeyYjsBacklogStore(valkey, 3600);
		await store.record("res-1", "u1");
		expect(valkey.expires.get("rt:yjs:res-1")).toBe(3600);
	});

	it("valkey store bounds the list to the most recent 50", async () => {
		const valkey = new FakeValkey();
		const store = new ValkeyYjsBacklogStore(valkey);
		for (let i = 0; i < 55; i += 1) {
			await store.record("res-1", `u${i}`);
		}
		const recent = await store.recent("res-1");
		expect(recent).toHaveLength(50);
		expect(recent[0]).toBe("u5");
	});
});
