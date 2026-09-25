import { createHash } from "node:crypto";
import type { Pool } from "pg";
import * as Y from "yjs";

const MAX_CURRENT_UPDATE_BYTES = 32 * 1024 * 1024;

export interface CurrentResourceStateProvider {
	readCurrentState(resourceId: string): Promise<Uint8Array | null>;
}

/**
 * Reads only the latest durable Resource Journal value and materializes it into
 * a fresh Y.Doc. Editor Core persists a full Yjs state update with each durable
 * revision; re-encoding the Y.Doc returns current content without exposing the
 * append-only Journal or its historical updates.
 */
export class PostgresCurrentResourceStateProvider
	implements CurrentResourceStateProvider
{
	constructor(private readonly pool: Pick<Pool, "query">) {}

	async readCurrentState(resourceId: string): Promise<Uint8Array | null> {
		const result = await this.pool.query<{
			update_bytes: Buffer;
			update_hash: string;
		}>(
			"SELECT update_bytes, update_hash " +
				"FROM collab.resource_update_journal " +
				"WHERE resource_id = $1::uuid AND durable_at IS NOT NULL " +
				"ORDER BY journal_seq DESC LIMIT 1",
			[resourceId],
		);
		const row = result.rows[0];
		if (!row) return null;
		if (row.update_bytes.byteLength > MAX_CURRENT_UPDATE_BYTES) {
			throw new Error("current resource state exceeds the Realtime limit");
		}
		const digest = createHash("sha256").update(row.update_bytes).digest("hex");
		if (digest !== row.update_hash) {
			throw new Error(
				"current resource state failed Journal hash verification",
			);
		}
		// Import and restore write domain markers into the Journal and
		// materialize their content as a checkpoint. They are not Yjs updates.
		const marker = Buffer.from(row.update_bytes).toString("utf8").trimStart();
		if (marker.startsWith("{") || marker.startsWith("restore@")) return null;

		const doc = new Y.Doc();
		try {
			Y.applyUpdate(doc, new Uint8Array(row.update_bytes));
			assertUpdateWasComplete(row.update_bytes, doc);
			return Y.encodeStateAsUpdate(doc);
		} finally {
			doc.destroy();
		}
	}
}

function assertUpdateWasComplete(update: Uint8Array, doc: Y.Doc): void {
	const decoded = Y.decodeUpdate(update);
	const stateVector = Y.decodeStateVector(Y.encodeStateVector(doc));
	for (const struct of decoded.structs) {
		const expectedClock = struct.id.clock + struct.length;
		if ((stateVector.get(struct.id.client) ?? 0) < expectedClock) {
			throw new Error("latest Journal entry is not a complete Yjs state");
		}
	}
}
