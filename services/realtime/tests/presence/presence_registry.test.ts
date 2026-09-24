import { describe, expect, it } from "vitest";

import { PresenceRegistry } from "../../src/presence/presence_registry.js";

describe("PresenceRegistry", () => {
	it("broadcasts join to the room and lists members", () => {
		const events: unknown[] = [];
		const registry = new PresenceRegistry((_room, envelope) => {
			events.push(envelope);
			return 1;
		});
		registry.join("res-1", "actor-a");
		registry.join("res-1", "actor-b");
		expect(registry.membersOf("res-1").sort()).toEqual(["actor-a", "actor-b"]);
		expect(events).toHaveLength(2);
	});

	it("broadcasts leave and prunes empty rooms", () => {
		const events: unknown[] = [];
		const registry = new PresenceRegistry((_room, envelope) => {
			events.push(envelope);
			return 1;
		});
		registry.join("res-1", "actor-a");
		expect(registry.leave("res-1", "actor-a")?.kind).toBe("leave");
		expect(registry.membersOf("res-1")).toEqual([]);
		expect(registry.leave("res-1", "actor-a")).toBeNull();
	});

	it("keeps rooms separate", () => {
		const registry = new PresenceRegistry(() => 1);
		registry.join("res-1", "a");
		registry.join("res-2", "b");
		expect(registry.membersOf("res-1")).toEqual(["a"]);
		expect(registry.membersOf("res-2")).toEqual(["b"]);
	});
});
