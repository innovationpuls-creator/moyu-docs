/**
 * Yjs document runtime (arch 05): the ONLY CRDT machinery for body sync.
 *
 * The editor works on a Y.Doc whose root map carries the document text
 * (Y.Text). Local edits are flushed as binary Yjs updates; remote updates are
 * applied through `applyUpdate`, which Yjs guarantees merges (start vector /
 * state vector based) so independent replicas converge to one state.
 */

import { IndexeddbPersistence } from "y-indexeddb";
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

export interface LocalDocumentIdentity {
	accountId: string;
	resourceId: string;
}

export interface PersistedDocumentHandle extends DocumentHandle {
	readonly identity: Readonly<LocalDocumentIdentity>;
	/**
	 * Stop local persistence and destroy the in-memory document. Cached updates
	 * remain in IndexedDB for the next open.
	 */
	dispose(): Promise<void>;
	/**
	 * Permanently remove this document's IndexedDB data. The caller must make
	 * the unsynced-data-loss decision explicitly before invoking this method.
	 */
	clearLocalData(options: {
		confirmDiscardUnsyncedChanges: true;
	}): Promise<void>;
}

function persistenceName(identity: LocalDocumentIdentity): string {
	if (!identity.accountId.trim() || !identity.resourceId.trim()) {
		throw new TypeError("accountId and resourceId must be non-empty");
	}
	return `dom:yjs:v1:account:${encodeURIComponent(identity.accountId)}:resource:${encodeURIComponent(identity.resourceId)}`;
}

/**
 * Open a locally persisted Y.Doc, resolving only after IndexedDB has hydrated
 * it. Callers must await this function before starting network synchronization.
 * An optional server snapshot is merged after local hydration and is never used
 * to replace local state.
 */
export async function openPersistedDocument(
	identity: LocalDocumentIdentity,
	seedUpdate?: Uint8Array,
): Promise<PersistedDocumentHandle> {
	if (typeof indexedDB === "undefined") {
		throw new Error("IndexedDB is unavailable in this runtime");
	}

	const name = persistenceName(identity);
	const handle = createDocument();
	const persistence = new IndexeddbPersistence(name, handle.doc);

	try {
		// Only `whenSynced` may resolve this wait. The database-open promise is
		// observed solely to surface a rejected open; a successful open does not
		// mean cached updates have finished hydrating the document.
		await new Promise<void>((resolve, reject) => {
			persistence.whenSynced.then(() => resolve(), reject);
			void persistence._db.catch(reject);
		});
		if (seedUpdate && seedUpdate.byteLength > 0) {
			handle.applyRemoteUpdate(seedUpdate);
		}
	} catch (error) {
		try {
			await persistence.destroy();
		} catch (cleanupError) {
			handle.doc.destroy();
			throw new AggregateError(
				[error, cleanupError],
				"Local document hydration and cleanup both failed",
			);
		}
		handle.doc.destroy();
		throw error;
	}

	let terminalState: "active" | "disposed" = "active";
	let terminalPromise: Promise<void> | undefined;
	const localIdentity = Object.freeze({
		accountId: identity.accountId,
		resourceId: identity.resourceId,
	});

	return {
		...handle,
		identity: localIdentity,
		async dispose(): Promise<void> {
			if (terminalState === "disposed") {
				return terminalPromise;
			}
			terminalState = "disposed";
			terminalPromise = persistence
				.destroy()
				.finally(() => handle.doc.destroy());
			return terminalPromise;
		},
		async clearLocalData(options): Promise<void> {
			if (options?.confirmDiscardUnsyncedChanges !== true) {
				throw new Error(
					"Clearing local document data requires explicit confirmation",
				);
			}
			if (terminalState === "disposed") {
				throw new Error(
					"Cannot clear local data after the document has been disposed",
				);
			}
			terminalState = "disposed";
			terminalPromise = persistence
				.clearData()
				.finally(() => handle.doc.destroy());
			return terminalPromise;
		},
	};
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
