/**
 * Yjs update backlog storage (arch 05 §initial sync): a bounded recent-update
 * list per resource subject. The in-memory store is the default (live-session
 * catch-up); a Valkey-backed store survives gateway restarts.
 */

export interface YjsBacklogStore {
	recent(resourceId: string): Promise<string[]>;
	record(resourceId: string, updateBase64: string): Promise<void>;
}

const BOUND = 50;
const KEY_PREFIX = "rt:yjs:";
const DEFAULT_TTL_SECONDS = 60 * 60; // idle backlogs self-clean after an hour

export class MemoryYjsBacklogStore implements YjsBacklogStore {
	private readonly updates = new Map<string, string[]>();

	async record(resourceId: string, updateBase64: string): Promise<void> {
		const recent = this.updates.get(resourceId) ?? [];
		recent.push(updateBase64);
		if (recent.length > BOUND) recent.splice(0, recent.length - BOUND);
		this.updates.set(resourceId, recent);
	}

	async recent(resourceId: string): Promise<string[]> {
		return [...(this.updates.get(resourceId) ?? [])];
	}
}

export interface ValkeyLike {
	rpush(key: string, ...values: string[]): Promise<unknown>;
	lrange(key: string, start: number, stop: number): Promise<string[]>;
	ltrim(key: string, start: number, stop: number): Promise<unknown>;
	expire(key: string, seconds: number): Promise<unknown>;
}

export class ValkeyYjsBacklogStore implements YjsBacklogStore {
	constructor(
		private readonly valkey: ValkeyLike,
		private readonly ttlSeconds: number = DEFAULT_TTL_SECONDS,
	) {}

	async record(resourceId: string, updateBase64: string): Promise<void> {
		const key = `${KEY_PREFIX}${resourceId}`;
		await this.valkey.rpush(key, updateBase64);
		await this.valkey.ltrim(key, -BOUND, -1);
		// refresh the TTL on activity so idle resources expire their backlog
		await this.valkey.expire(key, this.ttlSeconds);
	}

	async recent(resourceId: string): Promise<string[]> {
		return this.valkey.lrange(`${KEY_PREFIX}${resourceId}`, 0, BOUND - 1);
	}
}
