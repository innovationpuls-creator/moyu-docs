import { createHash } from "node:crypto";
import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import * as Y from "yjs";
import { PostgresCurrentResourceStateProvider } from "../../src/persistence/current_resource_state.js";

function storedRow(updateBytes: Uint8Array) {
	return {
		update_bytes: Buffer.from(updateBytes),
		update_hash: createHash("sha256").update(updateBytes).digest("hex"),
	};
}

function fakePool(rows: ReturnType<typeof storedRow>[]) {
	return {
		query: vi.fn(async () => ({ rows })),
	} as unknown as Pick<Pool, "query">;
}

describe("PostgresCurrentResourceStateProvider", () => {
	it("materializes one complete current Yjs update without reading Journal history", async () => {
		const source = new Y.Doc();
		source.getText("content").insert(0, "latest body");
		const update = Y.encodeStateAsUpdate(source);
		const pool = fakePool([storedRow(update)]);

		const state = await new PostgresCurrentResourceStateProvider(
			pool,
		).readCurrentState("00000000-0000-0000-0000-000000000001");

		const restored = new Y.Doc();
		if (state === null) throw new Error("expected current state");
		Y.applyUpdate(restored, state);
		expect(restored.getText("content").toString()).toBe("latest body");
		expect(pool.query).toHaveBeenCalledTimes(1);
		expect(String(vi.mocked(pool.query).mock.calls[0]?.[0])).toContain(
			"ORDER BY journal_seq DESC LIMIT 1",
		);
		restored.destroy();
		source.destroy();
	});

	it("returns null when no durable Yjs state exists", async () => {
		const provider = new PostgresCurrentResourceStateProvider(fakePool([]));
		expect(
			await provider.readCurrentState("00000000-0000-0000-0000-000000000001"),
		).toBeNull();
	});

	it("uses the checkpoint projection for import and restore journal markers", async () => {
		for (const marker of [
			Buffer.from('{"kind":"dom.resource.export.v1"}'),
			Buffer.from("restore@v3"),
		]) {
			const provider = new PostgresCurrentResourceStateProvider(
				fakePool([storedRow(marker)]),
			);
			expect(
				await provider.readCurrentState("00000000-0000-0000-0000-000000000001"),
			).toBeNull();
		}
	});

	it("rejects a row whose bytes do not match its durable hash", async () => {
		const row = storedRow(new Uint8Array([1]));
		row.update_hash = "0".repeat(64);
		const provider = new PostgresCurrentResourceStateProvider(fakePool([row]));
		await expect(
			provider.readCurrentState("00000000-0000-0000-0000-000000000001"),
		).rejects.toThrow("failed Journal hash verification");
	});

	it("rejects a delta update without its earlier Yjs structs", async () => {
		const source = new Y.Doc();
		const text = source.getText("content");
		text.insert(0, "first");
		const vector = Y.encodeStateVector(source);
		text.insert(text.length, " later");
		const delta = Y.encodeStateAsUpdate(source, vector);
		const provider = new PostgresCurrentResourceStateProvider(
			fakePool([storedRow(delta)]),
		);
		await expect(
			provider.readCurrentState("00000000-0000-0000-0000-000000000001"),
		).rejects.toThrow("not a complete Yjs state");
		source.destroy();
	});
});
