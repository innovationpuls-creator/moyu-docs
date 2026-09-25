import type { components } from "@dom/contracts/client-api";

export const UNBOUND_DRAFT_STORAGE_KEY = "draft_unsaved";
const DATABASE_NAME = "dom-resource-runtime";
const DATABASE_VERSION = 1;
const STORE_NAME = "resource-states";

export type ResourceMetadata = components["schemas"]["open-resource.schema"];

export interface ResourceGateway {
	openResource(resourceId: string): Promise<ResourceMetadata>;
}

interface StoredResourceState {
	accountId: string;
	resourceId: string;
	metadata: ResourceMetadata;
	update: ArrayBuffer;
	updatedAt: number;
}

export interface OpenResourceResult {
	resource: ResourceMetadata;
	localUpdate: Uint8Array | null;
	source: "server" | "offline-cache";
}

export class ResourceRuntime {
	constructor(
		private readonly gateway: ResourceGateway,
		private readonly databaseFactory: IDBFactory = indexedDB,
		private readonly localStorageLike: Pick<
			Storage,
			"getItem"
		> = window.localStorage,
	) {}

	async openResource(
		accountId: string,
		resourceId: string,
	): Promise<OpenResourceResult> {
		const cached = await this.readState(accountId, resourceId);
		try {
			const resource = await this.gateway.openResource(resourceId);
			if (cached) {
				await this.writeState(accountId, resourceId, cached.update, resource);
			}
			return {
				resource,
				localUpdate: cached?.update ?? null,
				source: "server",
			};
		} catch (error) {
			if (
				cached &&
				(error instanceof TypeError || navigator.onLine === false)
			) {
				return {
					resource: cached.metadata,
					localUpdate: cached.update,
					source: "offline-cache",
				};
			}
			throw error;
		}
	}

	persistLocalState(
		accountId: string,
		resourceId: string,
		update: Uint8Array,
		metadata: ResourceMetadata,
	): Promise<void> {
		return this.writeState(accountId, resourceId, update, metadata);
	}

	readUnboundRecoveryDraft(): string {
		return this.localStorageLike.getItem(UNBOUND_DRAFT_STORAGE_KEY) ?? "";
	}

	private async readState(
		accountId: string,
		resourceId: string,
	): Promise<{ metadata: ResourceMetadata; update: Uint8Array } | null> {
		const database = await this.openDatabase();
		try {
			const row = await new Promise<StoredResourceState | undefined>(
				(resolve, reject) => {
					const request = database
						.transaction(STORE_NAME, "readonly")
						.objectStore(STORE_NAME)
						.get([accountId, resourceId]);
					request.onsuccess = () =>
						resolve(request.result as StoredResourceState | undefined);
					request.onerror = () => reject(request.error);
				},
			);
			return row
				? { metadata: row.metadata, update: new Uint8Array(row.update) }
				: null;
		} finally {
			database.close();
		}
	}

	private async writeState(
		accountId: string,
		resourceId: string,
		update: Uint8Array,
		metadata: ResourceMetadata,
	): Promise<void> {
		const database = await this.openDatabase();
		try {
			await new Promise<void>((resolve, reject) => {
				const transaction = database.transaction(STORE_NAME, "readwrite");
				transaction.objectStore(STORE_NAME).put({
					accountId,
					resourceId,
					metadata,
					update: update.slice().buffer,
					updatedAt: Date.now(),
				} satisfies StoredResourceState);
				transaction.oncomplete = () => resolve();
				transaction.onerror = () => reject(transaction.error);
				transaction.onabort = () => reject(transaction.error);
			});
		} finally {
			database.close();
		}
	}

	private openDatabase(): Promise<IDBDatabase> {
		return new Promise((resolve, reject) => {
			const request = this.databaseFactory.open(
				DATABASE_NAME,
				DATABASE_VERSION,
			);
			request.onupgradeneeded = () => {
				const database = request.result;
				if (!database.objectStoreNames.contains(STORE_NAME)) {
					database.createObjectStore(STORE_NAME, {
						keyPath: ["accountId", "resourceId"],
					});
				}
			};
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
			request.onblocked = () =>
				reject(new Error("Resource storage is blocked"));
		});
	}
}
