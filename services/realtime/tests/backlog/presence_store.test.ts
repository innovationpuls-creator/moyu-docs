import { describe, expect, it } from "vitest";

import {
	MemoryPresenceStore,
	ValkeyPresenceStore,
} from "../../src/backlog/presence_store.js";

class FakeValkey {
	sets = new Map<string, Set<string>>();
	expires = new Map<string, number>();

	async sadd(key: string, ...values: string[]): Promise<number> {
		const set = this.sets.get(key) ?? new Set<string>();
		values.forEach((v) => {
			set.add(v);
		});
		this.sets.set(key, set);
		return set.size;
	}

	async srem(key: string, ...values: string[]): Promise<number> {
		const set = this.sets.get(key) ?? new Set<string>();
		let removed = 0;
		for (const v of values) removed += set.delete(v) ? 1 : 0;
		return removed;
	}

	async smembers(key: string): Promise<string[]> {
		return [...(this.sets.get(key) ?? [])];
	}

	async expire(key: string, seconds: number): Promise<number> {
		this.expires.set(key, seconds);
		return 1;
	}
}

describe("presence stores", () => {
	it("memory store tracks join/leave", async () => {
		const store = new MemoryPresenceStore();
		await store.join("res-1", "a");
		await store.join("res-1", "b");
		expect(await store.peers("res-1")).toEqual(["a", "b"]);
		await store.leave("res-1", "a");
		expect(await store.peers("res-1")).toEqual(["b"]);
	});

	it("valkey store round-trips members and refreshes the TTL", async () => {
		const valkey = new FakeValkey();
		const store = new ValkeyPresenceStore(valkey, 600);
		await store.join("res-1", "a");
		await store.join("res-1", "b");
		expect(await store.peers("res-1")).toEqual(["a", "b"]);
		expect(valkey.expires.get("rt:presence:res-1")).toBe(600);
		await store.leave("res-1", "a");
		expect(await store.peers("res-1")).toEqual(["b"]);
	});
});
