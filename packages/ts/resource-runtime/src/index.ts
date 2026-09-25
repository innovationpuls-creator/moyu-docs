import type { components } from "@dom/contracts/client-api";

export const UNBOUND_DRAFT_STORAGE_KEY = "draft_unsaved";
export const LAST_ACCOUNT_ID_STORAGE_KEY =
	"dom:resource-runtime:last-account-id";

const DATABASE_NAME = "dom-resource-runtime";
const DATABASE_VERSION = 2;
const RESOURCE_STORE = "resource-states";
const SNAPSHOT_STORE = "resource-snapshots";
const SNAPSHOT_INDEX = "by-account-resource";

export type ResourceMetadata = components["schemas"]["open-resource.schema"];

export interface ResourceGateway {
	openResource(resourceId: string): Promise<ResourceMetadata>;
}

export interface LocalResourceSnapshot {
	replicaId: string;
	revision: number;
	acceptedRevision: number;
	durableRevision: number;
	update: Uint8Array;
	updatedAt: number;
}

export interface ConfirmedLocalRevisions {
	acceptedRevision?: number;
	durableRevision?: number;
}

export interface OpenResourceResult {
	resource: ResourceMetadata;
	/**
	 * Compatibility view for callers that only know about one local snapshot.
	 * It is null when multiple tabs have independent local state; callers must
	 * merge `localSnapshots` through editor-core instead of choosing one.
	 */
	localUpdate: Uint8Array | null;
	localSnapshots: LocalResourceSnapshot[];
	source: "server" | "offline-cache";
	/** A cache failure is visible to callers without blocking an online open. */
	cacheError?: string;
}

export interface ResourceRuntimeOptions {
	databaseFactory?: IDBFactory;
	localStorageLike?: Pick<Storage, "getItem" | "setItem">;
	replicaId?: string;
	broadcastChannelFactory?: (name: string) => BroadcastChannel;
}

export interface LocalResourceUpdateEvent {
	replicaId: string;
	revision: number;
	update: Uint8Array;
}

export interface UnsyncedResource {
	resource: ResourceMetadata;
	snapshots: LocalResourceSnapshot[];
}

interface StoredResourceState {
	accountId: string;
	resourceId: string;
	metadata: ResourceMetadata;
	/** v1 compatibility field; v2 writes snapshots to the separate store. */
	update?: ArrayBuffer;
	updatedAt: number;
}

interface StoredResourceSnapshot {
	accountId: string;
	resourceId: string;
	replicaId: string;
	revision: number;
	acceptedRevision?: number;
	durableRevision?: number;
	update: ArrayBuffer;
	updatedAt: number;
}

interface CachedResourceState {
	metadata: ResourceMetadata | null;
	localSnapshots: LocalResourceSnapshot[];
}

interface BroadcastUpdateMessage {
	type: "local-resource-update";
	accountId: string;
	resourceId: string;
	replicaId: string;
	revision: number;
	update: ArrayBuffer;
}

function validateIdentity(accountId: string, resourceId: string): void {
	if (!accountId.trim() || !resourceId.trim()) {
		throw new TypeError("accountId and resourceId must be non-empty");
	}
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function isOfflineError(error: unknown): boolean {
	return (
		error instanceof TypeError ||
		(typeof navigator !== "undefined" && navigator.onLine === false)
	);
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
	return new Promise((resolve, reject) => {
		transaction.oncomplete = () => resolve();
		transaction.onerror = () => reject(transaction.error);
		transaction.onabort = () => reject(transaction.error);
	});
}

function cloneBytes(bytes: Uint8Array): Uint8Array {
	return new Uint8Array(bytes);
}

function copyToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
	return new Uint8Array(bytes).buffer;
}

export class ResourceRuntime {
	private readonly subscriptions = new Set<() => void>();
	private disposed = false;
	private readonly databaseFactory: IDBFactory | undefined;
	private readonly localStorageLike:
		| Pick<Storage, "getItem" | "setItem">
		| undefined;
	private readonly replicaId: string | undefined;
	private readonly broadcastChannelFactory:
		| ((name: string) => BroadcastChannel)
		| undefined;

	constructor(
		private readonly gateway: ResourceGateway,
		options: ResourceRuntimeOptions = {},
	) {
		this.databaseFactory = options.databaseFactory ?? globalThis.indexedDB;
		this.localStorageLike = options.localStorageLike ?? globalThis.localStorage;
		this.replicaId = options.replicaId ?? globalThis.crypto?.randomUUID();
		this.broadcastChannelFactory =
			options.broadcastChannelFactory ??
			(typeof BroadcastChannel === "undefined"
				? undefined
				: (name) => new BroadcastChannel(name));
	}

	async openResource(
		accountId: string,
		resourceId: string,
	): Promise<OpenResourceResult> {
		this.assertActive();
		validateIdentity(accountId, resourceId);
		let cached: CachedResourceState | null = null;
		let cacheError: string | undefined;
		try {
			cached = await this.readState(accountId, resourceId);
		} catch (error) {
			cacheError = errorMessage(error);
		}

		try {
			const resource = await this.gateway.openResource(resourceId);
			try {
				await this.writeMetadata(accountId, resourceId, resource);
				this.rememberAccountId(accountId);
			} catch (error) {
				cacheError = errorMessage(error);
			}
			const localSnapshots = cached?.localSnapshots ?? [];
			return {
				resource,
				localUpdate:
					localSnapshots.length === 1
						? cloneBytes(localSnapshots[0].update)
						: null,
				localSnapshots,
				source: "server",
				...(cacheError ? { cacheError } : {}),
			};
		} catch (error) {
			if (cached?.metadata && isOfflineError(error)) {
				return {
					resource: cached.metadata,
					localUpdate:
						cached.localSnapshots.length === 1
							? cloneBytes(cached.localSnapshots[0].update)
							: null,
					localSnapshots: cached.localSnapshots,
					source: "offline-cache",
					...(cacheError ? { cacheError } : {}),
				};
			}
			if (cacheError && isOfflineError(error)) {
				throw new AggregateError(
					[error, new Error(cacheError)],
					"Resource is offline and its local cache could not be read",
				);
			}
			throw error;
		}
	}

	/** Store a full editor-core Yjs state snapshot without importing Yjs here. */
	async persistLocalState(
		accountId: string,
		resourceId: string,
		update: Uint8Array,
		metadata: ResourceMetadata,
	): Promise<LocalResourceSnapshot> {
		this.assertActive();
		validateIdentity(accountId, resourceId);
		if (metadata.resourceId !== resourceId) {
			throw new TypeError("Resource metadata must match resourceId");
		}
		if (!this.replicaId) {
			throw new Error("A browser crypto.randomUUID implementation is required");
		}
		if (update.byteLength === 0) {
			throw new TypeError("A local Yjs state snapshot must not be empty");
		}

		const database = await this.openDatabase();
		let snapshot: StoredResourceSnapshot | undefined;
		try {
			const transaction = database.transaction(
				[RESOURCE_STORE, SNAPSHOT_STORE],
				"readwrite",
			);
			const done = transactionDone(transaction);
			const resources = transaction.objectStore(RESOURCE_STORE);
			const snapshots = transaction.objectStore(SNAPSHOT_STORE);
			const key = [accountId, resourceId, this.replicaId];
			const read = snapshots.get(key);
			read.onsuccess = () => {
				const prior = read.result as StoredResourceSnapshot | undefined;
				snapshot = {
					accountId,
					resourceId,
					replicaId: this.replicaId as string,
					revision: (prior?.revision ?? 0) + 1,
					acceptedRevision: prior?.acceptedRevision ?? 0,
					durableRevision: prior?.durableRevision ?? 0,
					update: copyToArrayBuffer(update),
					updatedAt: Date.now(),
				};
				snapshots.put(snapshot);
				resources.put({
					accountId,
					resourceId,
					metadata,
					updatedAt: snapshot.updatedAt,
				} satisfies StoredResourceState);
			};
			await done;
		} finally {
			database.close();
		}
		if (!snapshot) {
			throw new Error("Local resource snapshot was not committed");
		}
		this.publishLocalUpdate(accountId, resourceId, snapshot);
		return {
			replicaId: snapshot.replicaId,
			revision: snapshot.revision,
			update: new Uint8Array(snapshot.update),
			acceptedRevision: snapshot.acceptedRevision ?? 0,
			durableRevision: snapshot.durableRevision ?? 0,
			updatedAt: snapshot.updatedAt,
		};
	}

	/**
	 * Advance locally stored markers only after a server receipt has been mapped
	 * to this replica's exact local revision. Socket send and online state are
	 * not evidence. Older receipts are ignored; future revisions are rejected.
	 */
	async recordConfirmedRevisions(
		accountId: string,
		resourceId: string,
		replicaId: string,
		confirmed: ConfirmedLocalRevisions,
	): Promise<LocalResourceSnapshot> {
		this.assertActive();
		validateIdentity(accountId, resourceId);
		if (!replicaId.trim()) throw new TypeError("replicaId must be non-empty");
		const entries = Object.entries(confirmed);
		if (entries.length === 0) {
			throw new TypeError("At least one confirmed revision is required");
		}
		for (const [name, revision] of entries) {
			if (!Number.isSafeInteger(revision) || (revision as number) < 0) {
				throw new TypeError(`${name} must be a non-negative safe integer`);
			}
		}

		const database = await this.openDatabase();
		let snapshot: StoredResourceSnapshot | undefined;
		let validationError: Error | undefined;
		try {
			const transaction = database.transaction(SNAPSHOT_STORE, "readwrite");
			const done = transactionDone(transaction);
			const store = transaction.objectStore(SNAPSHOT_STORE);
			const request = store.get([accountId, resourceId, replicaId]);
			request.onsuccess = () => {
				const prior = request.result as StoredResourceSnapshot | undefined;
				if (!prior) {
					validationError = new Error("Local replica snapshot was not found");
					transaction.abort();
					return;
				}
				const acceptedRevision =
					confirmed.acceptedRevision === undefined
						? (prior.acceptedRevision ?? 0)
						: Math.max(prior.acceptedRevision ?? 0, confirmed.acceptedRevision);
				const durableRevision =
					confirmed.durableRevision === undefined
						? (prior.durableRevision ?? 0)
						: Math.max(prior.durableRevision ?? 0, confirmed.durableRevision);
				if (
					acceptedRevision > prior.revision ||
					durableRevision > prior.revision
				) {
					validationError = new RangeError(
						"A receipt cannot confirm a revision that has not been persisted locally",
					);
					transaction.abort();
					return;
				}
				snapshot = {
					...prior,
					acceptedRevision,
					durableRevision,
				};
				store.put(snapshot);
			};
			try {
				await done;
			} catch (error) {
				if (validationError) throw validationError;
				throw error;
			}
		} finally {
			database.close();
		}
		if (!snapshot) throw new Error("Confirmed revision was not committed");
		return {
			replicaId: snapshot.replicaId,
			revision: snapshot.revision,
			acceptedRevision: snapshot.acceptedRevision ?? 0,
			durableRevision: snapshot.durableRevision ?? 0,
			update: new Uint8Array(snapshot.update),
			updatedAt: snapshot.updatedAt,
		};
	}

	subscribeLocalUpdates(
		accountId: string,
		resourceId: string,
		handler: (event: LocalResourceUpdateEvent) => void,
	): () => void {
		this.assertActive();
		validateIdentity(accountId, resourceId);
		if (!this.broadcastChannelFactory) {
			throw new Error("BroadcastChannel is unavailable in this browser");
		}
		const channel = this.broadcastChannelFactory(
			this.localChannelName(accountId, resourceId),
		);
		const listener = (event: MessageEvent<unknown>): void => {
			const message = event.data as Partial<BroadcastUpdateMessage> | null;
			if (
				message?.type !== "local-resource-update" ||
				message.accountId !== accountId ||
				message.resourceId !== resourceId ||
				typeof message.replicaId !== "string" ||
				typeof message.revision !== "number" ||
				!(message.update instanceof ArrayBuffer)
			) {
				return;
			}
			handler({
				replicaId: message.replicaId,
				revision: message.revision,
				update: new Uint8Array(message.update),
			});
		};
		channel.addEventListener("message", listener);
		let subscribed = true;
		const unsubscribe = (): void => {
			if (!subscribed) return;
			subscribed = false;
			channel.removeEventListener("message", listener);
			channel.close();
			this.subscriptions.delete(unsubscribe);
		};
		this.subscriptions.add(unsubscribe);
		return unsubscribe;
	}

	/** Close local update subscriptions without deleting any cached content. */
	dispose(): void {
		if (this.disposed) return;
		this.disposed = true;
		for (const unsubscribe of [...this.subscriptions]) unsubscribe();
	}

	rememberAccountId(accountId: string): void {
		this.assertActive();
		if (!accountId.trim()) throw new TypeError("accountId must be non-empty");
		this.localStorageLike?.setItem(LAST_ACCOUNT_ID_STORAGE_KEY, accountId);
	}

	getCachedAccountId(): string | null {
		this.assertActive();
		return this.localStorageLike?.getItem(LAST_ACCOUNT_ID_STORAGE_KEY) ?? null;
	}

	clearCachedAccountId(): void {
		this.assertActive();
		this.localStorageLike?.setItem(LAST_ACCOUNT_ID_STORAGE_KEY, "");
	}

	async listUnsyncedResources(accountId: string): Promise<UnsyncedResource[]> {
		this.assertActive();
		if (!accountId.trim()) throw new TypeError("accountId must be non-empty");
		const database = await this.openDatabase();
		try {
			const transaction = database.transaction(
				[RESOURCE_STORE, SNAPSHOT_STORE],
				"readonly",
			);
			const done = transactionDone(transaction);
			const accountRange = IDBKeyRange.bound(
				[accountId, ""],
				[accountId, "\uffff"],
			);
			const resourcesRequest = transaction
				.objectStore(RESOURCE_STORE)
				.getAll(accountRange);
			const snapshotsRequest = transaction
				.objectStore(SNAPSHOT_STORE)
				.index(SNAPSHOT_INDEX)
				.getAll(accountRange);
			const [resources, rows] = await Promise.all([
				requestResult(resourcesRequest) as Promise<StoredResourceState[]>,
				requestResult(snapshotsRequest) as Promise<StoredResourceSnapshot[]>,
			]);
			await done;

			const snapshotsByResource = new Map<string, LocalResourceSnapshot[]>();
			const unsyncedResourceIds = new Set<string>();
			for (const row of rows) {
				const snapshots = snapshotsByResource.get(row.resourceId) ?? [];
				snapshots.push({
					replicaId: row.replicaId,
					revision: row.revision,
					acceptedRevision: row.acceptedRevision ?? 0,
					durableRevision: row.durableRevision ?? 0,
					update: new Uint8Array(row.update),
					updatedAt: row.updatedAt,
				});
				snapshotsByResource.set(row.resourceId, snapshots);
				if (row.revision > (row.durableRevision ?? 0)) {
					unsyncedResourceIds.add(row.resourceId);
				}
			}

			return resources
				.filter((state) => unsyncedResourceIds.has(state.resourceId))
				.map((state) => ({
					resource: state.metadata,
					snapshots: snapshotsByResource.get(state.resourceId) ?? [],
				}));
		} finally {
			database.close();
		}
	}

	readUnboundRecoveryDraft(): string {
		this.assertActive();
		return this.localStorageLike?.getItem(UNBOUND_DRAFT_STORAGE_KEY) ?? "";
	}

	/** Explicit destructive operation; normal dispose/logout never calls this. */
	async clearLocalResource(
		accountId: string,
		resourceId: string,
		options: { confirmDiscardUnsyncedChanges: true },
	): Promise<void> {
		this.assertActive();
		validateIdentity(accountId, resourceId);
		if (options?.confirmDiscardUnsyncedChanges !== true) {
			throw new Error(
				"Clearing local resource data requires explicit confirmation",
			);
		}
		const database = await this.openDatabase();
		try {
			const transaction = database.transaction(
				[RESOURCE_STORE, SNAPSHOT_STORE],
				"readwrite",
			);
			const done = transactionDone(transaction);
			transaction.objectStore(RESOURCE_STORE).delete([accountId, resourceId]);
			const snapshots = transaction.objectStore(SNAPSHOT_STORE);
			const keys = snapshots
				.index(SNAPSHOT_INDEX)
				.getAllKeys(IDBKeyRange.only([accountId, resourceId]));
			keys.onsuccess = () => {
				for (const key of keys.result) snapshots.delete(key);
			};
			await done;
		} finally {
			database.close();
		}
	}

	private async readState(
		accountId: string,
		resourceId: string,
	): Promise<CachedResourceState | null> {
		const database = await this.openDatabase();
		try {
			const transaction = database.transaction(
				[RESOURCE_STORE, SNAPSHOT_STORE],
				"readonly",
			);
			const done = transactionDone(transaction);
			const stateRequest = transaction
				.objectStore(RESOURCE_STORE)
				.get([accountId, resourceId]);
			const snapshotsRequest = transaction
				.objectStore(SNAPSHOT_STORE)
				.index(SNAPSHOT_INDEX)
				.getAll(IDBKeyRange.only([accountId, resourceId]));
			const [state, rows] = await Promise.all([
				requestResult(stateRequest) as Promise<StoredResourceState | undefined>,
				requestResult(snapshotsRequest) as Promise<StoredResourceSnapshot[]>,
			]);
			await done;

			const localSnapshots = rows
				.map((row) => ({
					replicaId: row.replicaId,
					revision: row.revision,
					acceptedRevision: row.acceptedRevision ?? 0,
					durableRevision: row.durableRevision ?? 0,
					update: new Uint8Array(row.update),
					updatedAt: row.updatedAt,
				}))
				.sort(
					(left, right) =>
						left.updatedAt - right.updatedAt ||
						left.replicaId.localeCompare(right.replicaId),
				);
			if (state?.update && state.update.byteLength > 0) {
				localSnapshots.push({
					replicaId: "legacy-v1",
					revision: 0,
					acceptedRevision: 0,
					durableRevision: 0,
					update: new Uint8Array(state.update),
					updatedAt: state.updatedAt,
				});
			}
			if (!state && localSnapshots.length === 0) return null;
			return {
				metadata: state?.metadata ?? null,
				localSnapshots,
			};
		} finally {
			database.close();
		}
	}

	private async writeMetadata(
		accountId: string,
		resourceId: string,
		metadata: ResourceMetadata,
	): Promise<void> {
		const database = await this.openDatabase();
		try {
			const transaction = database.transaction(RESOURCE_STORE, "readwrite");
			const done = transactionDone(transaction);
			const store = transaction.objectStore(RESOURCE_STORE);
			const request = store.get([accountId, resourceId]);
			request.onsuccess = () => {
				const prior = request.result as StoredResourceState | undefined;
				store.put({
					...prior,
					accountId,
					resourceId,
					metadata,
					updatedAt: Date.now(),
				} satisfies StoredResourceState);
			};
			await done;
		} finally {
			database.close();
		}
	}

	private publishLocalUpdate(
		accountId: string,
		resourceId: string,
		snapshot: StoredResourceSnapshot,
	): void {
		if (!this.broadcastChannelFactory) return;
		const channel = this.broadcastChannelFactory(
			this.localChannelName(accountId, resourceId),
		);
		const message: BroadcastUpdateMessage = {
			type: "local-resource-update",
			accountId,
			resourceId,
			replicaId: snapshot.replicaId,
			revision: snapshot.revision,
			update: snapshot.update.slice(0),
		};
		channel.postMessage(message);
		channel.close();
	}

	private localChannelName(accountId: string, resourceId: string): string {
		return `dom:resource-runtime:v2:${encodeURIComponent(accountId)}:${encodeURIComponent(resourceId)}`;
	}

	private openDatabase(): Promise<IDBDatabase> {
		if (!this.databaseFactory) {
			return Promise.reject(new Error("IndexedDB is unavailable"));
		}
		return new Promise((resolve, reject) => {
			let settled = false;
			const request = this.databaseFactory?.open(
				DATABASE_NAME,
				DATABASE_VERSION,
			);
			if (!request) {
				reject(new Error("IndexedDB is unavailable"));
				return;
			}
			request.onupgradeneeded = (event) => {
				const database = request.result;
				const oldVersion = (event as IDBVersionChangeEvent).oldVersion;
				if (!database.objectStoreNames.contains(RESOURCE_STORE)) {
					database.createObjectStore(RESOURCE_STORE, {
						keyPath: ["accountId", "resourceId"],
					});
				}
				if (!database.objectStoreNames.contains(SNAPSHOT_STORE)) {
					const snapshots = database.createObjectStore(SNAPSHOT_STORE, {
						keyPath: ["accountId", "resourceId", "replicaId"],
					});
					snapshots.createIndex(SNAPSHOT_INDEX, ["accountId", "resourceId"]);
				}
				if (oldVersion > 0 && oldVersion < 2) {
					const transaction = request.transaction;
					if (!transaction) {
						throw new Error("Resource storage upgrade transaction is missing");
					}
					const resources = transaction.objectStore(RESOURCE_STORE);
					const snapshots = transaction.objectStore(SNAPSHOT_STORE);
					const cursorRequest = resources.openCursor();
					cursorRequest.onsuccess = () => {
						const cursor = cursorRequest.result;
						if (!cursor) return;
						const state = cursor.value as StoredResourceState;
						if (state.update instanceof ArrayBuffer) {
							snapshots.put({
								accountId: state.accountId,
								resourceId: state.resourceId,
								replicaId: "legacy-v1",
								revision: 0,
								acceptedRevision: 0,
								durableRevision: 0,
								update: state.update,
								updatedAt: state.updatedAt,
							} satisfies StoredResourceSnapshot);
						}
						cursor.continue();
					};
				}
			};
			request.onsuccess = () => {
				const database = request.result;
				if (settled) {
					database.close();
					return;
				}
				settled = true;
				database.onversionchange = () => database.close();
				resolve(database);
			};
			request.onerror = () => {
				if (settled) return;
				settled = true;
				reject(request.error);
			};
			request.onblocked = () => {
				if (settled) return;
				settled = true;
				reject(new Error("Resource storage is blocked"));
			};
		});
	}

	private assertActive(): void {
		if (this.disposed) throw new Error("ResourceRuntime has been disposed");
	}
}
