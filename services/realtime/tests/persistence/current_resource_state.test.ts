import { createHash } from "node:crypto";
import type { Pool } from "pg";
import { describe, expect, it } from "vitest";
import * as Y from "yjs";
import { PostgresCurrentResourceStateProvider } from "../../src/persistence/current_resource_state.js";
import { snapshotFromDoc } from "../../src/persistence/resource_content.js";

interface JournalRow {
	journal_seq: number;
	update_bytes: Buffer;
	update_hash: string;
	mutation_kind: string | null;
}

interface CheckpointRow {
	base_journal_seq: number;
	snapshot: unknown;
}

function journalRow(journalSeq: number, bytes: Uint8Array): JournalRow {
	return {
		journal_seq: journalSeq,
		update_bytes: Buffer.from(bytes),
		update_hash: createHash("sha256").update(bytes).digest("hex"),
		mutation_kind: null,
	};
}

function fakePool(
	journalRows: JournalRow[],
	checkpoints: CheckpointRow[] = [],
): Pick<Pool, "connect"> {
	return {
		connect: async () => ({
			query: async (statement: string, values: unknown[] = []) => {
				if (statement.includes("SELECT lifecycle FROM core.resources")) {
					return { rows: [{ lifecycle: "Active" }] };
				}
				if (statement.includes("COALESCE(MAX(journal_seq),0)")) {
					return {
						rows: [
							{
								max_seq: Math.max(
									0,
									...journalRows.map((row) => row.journal_seq),
								),
							},
						],
					};
				}
				if (statement.includes("SELECT journal_seq,update_bytes")) {
					const maxSeq = Number(values[1]);
					return {
						rows: journalRows
							.filter((row) => row.journal_seq <= maxSeq)
							.sort((left, right) => right.journal_seq - left.journal_seq),
					};
				}
				if (statement.includes("SELECT base_journal_seq,snapshot")) {
					const beforeSeq = Number(values[1]);
					return {
						rows: checkpoints
							.filter((row) => row.base_journal_seq < beforeSeq)
							.sort(
								(left, right) => right.base_journal_seq - left.base_journal_seq,
							),
					};
				}
				return { rows: [] };
			},
			release: () => undefined,
		}),
	} as unknown as Pick<Pool, "connect">;
}

function yjsState(text: string): Uint8Array {
	const source = new Y.Doc();
	const fragment = source.getXmlFragment("prosemirror");
	const paragraph = new Y.XmlElement("paragraph");
	const body = new Y.XmlText();
	if (text) body.insert(0, text);
	paragraph.insert(0, [body]);
	fragment.insert(0, [paragraph]);
	const state = Y.encodeStateAsUpdate(source);
	source.destroy();
	return state;
}

describe("PostgresCurrentResourceStateProvider", () => {
	const resourceId = "00000000-0000-0000-0000-000000000001";

	it("materializes the latest complete Yjs state as an editor-readable document", async () => {
		const update = yjsState("latest body");
		const state = await new PostgresCurrentResourceStateProvider(
			fakePool([
				journalRow(2, update),
				journalRow(1, yjsState("earlier body")),
			]),
		).readCurrentState(resourceId);

		const restored = new Y.Doc();
		Y.applyUpdate(restored, state);
		expect(snapshotFromDoc(restored).text).toBe("latest body");
		restored.destroy();
	});

	it("returns an empty Editor Core document when a Resource has no Journal state", async () => {
		const state = await new PostgresCurrentResourceStateProvider(
			fakePool([]),
		).readCurrentState(resourceId);
		const restored = new Y.Doc();
		Y.applyUpdate(restored, state);
		expect(snapshotFromDoc(restored)).toEqual({
			text: "",
			nodes: [{ kind: "paragraph", children: [] }],
		});
		restored.destroy();
	});

	it("uses a semantic checkpoint to recover legacy import and restore markers", async () => {
		for (const marker of [
			Buffer.from('{"kind":"dom.resource.export.v1"}'),
			Buffer.from("restore@v3"),
		]) {
			const state = await new PostgresCurrentResourceStateProvider(
				fakePool(
					[journalRow(3, marker)],
					[
						{
							base_journal_seq: 3,
							snapshot: {
								text: "recovered body",
								nodes: [
									{
										kind: "paragraph",
										children: [{ kind: "text", text: "recovered body" }],
									},
								],
							},
						},
					],
				),
			).readCurrentState(resourceId);
			const restored = new Y.Doc();
			Y.applyUpdate(restored, state);
			expect(snapshotFromDoc(restored).text).toBe("recovered body");
			restored.destroy();
		}
	});

	it("rejects a row whose bytes do not match its durable hash", async () => {
		const row = journalRow(1, yjsState("body"));
		row.update_hash = "0".repeat(64);
		await expect(
			new PostgresCurrentResourceStateProvider(
				fakePool([row]),
			).readCurrentState(resourceId),
		).rejects.toThrow("failed hash verification");
	});

	it("rejects a delta update without its earlier Yjs structs", async () => {
		const source = new Y.Doc();
		const text = source.getText("content");
		text.insert(0, "first");
		const vector = Y.encodeStateVector(source);
		text.insert(text.length, " later");
		const delta = Y.encodeStateAsUpdate(source, vector);
		await expect(
			new PostgresCurrentResourceStateProvider(
				fakePool([journalRow(1, delta)]),
			).readCurrentState(resourceId),
		).rejects.toThrow("not a complete Yjs state");
		source.destroy();
	});
});
