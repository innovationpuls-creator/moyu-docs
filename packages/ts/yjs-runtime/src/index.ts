/**
 * Yjs document runtime (arch 05): the ONLY CRDT machinery for body sync.
 *
 * The editor works on a Y.Doc whose root map carries the document text
 * (Y.Text). Local edits are flushed as binary Yjs updates; remote updates are
 * applied through `applyUpdate`, which Yjs guarantees merges (start vector /
 * state vector based) so independent replicas converge to one state.
 */

import * as Y from "yjs";

export interface DocumentHandle {
	doc: Y.Doc;
	flushUpdates(): Uint8Array[];
	applyRemoteUpdate(update: Uint8Array): void;
	exportState(): Uint8Array;
	text(): string;
	/** State-vector anchor for incremental sync (arch 05 §172). */
	stateVector(): Uint8Array;
}

export function createDocument(seedUpdate?: Uint8Array): DocumentHandle {
	const doc = new Y.Doc();
	if (seedUpdate && seedUpdate.byteLength > 0) {
		Y.applyUpdate(doc, seedUpdate);
	}
	const pending: Uint8Array[] = [];
	doc.on("update", (_update: Uint8Array, origin: unknown) => {
		if (origin === "remote") return;
		pending.push(_update);
	});
	return {
		doc,
		flushUpdates(): Uint8Array[] {
			const batch = pending.splice(0, pending.length);
			// All pending updates accumulated; a full state diff is not needed
			// because every flush returns the exact local increments.
			return batch;
		},
		applyRemoteUpdate(update: Uint8Array): void {
			Y.applyUpdate(doc, update, "remote");
		},
		exportState(): Uint8Array {
			return Y.encodeStateAsUpdate(doc);
		},
		text(): string {
			const text = doc.getText("content");
			return text.toString();
		},
		stateVector(): Uint8Array {
			return Y.encodeStateVector(doc);
		},
	};
}

/** Replace the whole document text deterministically (delete-all + insert
 * creates unique Yjs items, so concurrent replicas converge). */
export function setText(handle: DocumentHandle, value: string): void {
	const text = handle.doc.getText("content");
	if (text.toString() === value) return;
	handle.doc.transact(() => {
		text.delete(0, text.length);
		text.insert(0, value);
	});
}

export function mergeStates(updates: Uint8Array[]): Uint8Array {
	const merged = new Y.Doc();
	for (const update of updates) {
		Y.applyUpdate(merged, update);
	}
	return Y.encodeStateAsUpdate(merged);
}

/** State-vector of the document (arch 05 §incremental sync): the anchor for
 * ``diffSince`` — what a remote replica already has. */
export function stateVector(handle: DocumentHandle): Uint8Array {
	return Y.encodeStateVector(handle.doc);
}

/** The minimal update that takes a replica AT the given state-vector to the
 * document's full state; empty when the replica is already caught up. */
export function diffSince(
	handle: DocumentHandle,
	vector: Uint8Array,
): Uint8Array {
	return Y.encodeStateAsUpdate(handle.doc, vector);
}
