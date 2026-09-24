/**
 * Presence roster persistence (arch 05): peer NAMES per resource live in a
 * Valkey set so a roster survives gateway restarts (within the TTL window)
 * and multi-gateway deployments see each other's members. Live connection
 * counts remain authoritative; the persisted set is a coarse-grained seed.
 */

export interface PresenceStore {
	join(resourceId: string, actorId: string): Promise<void>;
	leave(resourceId: string, actorId: string): Promise<void>;
	peers(resourceId: string): Promise<string[]>;
}

const KEY_PREFIX = "rt:presence:";
const DEFAULT_TTL_SECONDS = 10 * 60;

export class MemoryPresenceStore implements PresenceStore {
	private readonly members = new Map<string, Set<string>>();

	async join(resourceId: string, actorId: string): Promise<void> {
		const set = this.members.get(resourceId) ?? new Set<string>();
		set.add(actorId);
		this.members.set(resourceId, set);
	}

	async leave(resourceId: string, actorId: string): Promise<void> {
		this.members.get(resourceId)?.delete(actorId);
	}

	async peers(resourceId: string): Promise<string[]> {
		return [...(this.members.get(resourceId) ?? [])];
	}
}

export interface ValkeySetLike {
	sadd(key: string, ...values: string[]): Promise<unknown>;
	srem(key: string, ...values: string[]): Promise<unknown>;
	smembers(key: string): Promise<string[]>;
	expire(key: string, seconds: number): Promise<unknown>;
}

export class ValkeyPresenceStore implements PresenceStore {
	constructor(
		private readonly valkey: ValkeySetLike,
		private readonly ttlSeconds: number = DEFAULT_TTL_SECONDS,
	) {}

	async join(resourceId: string, actorId: string): Promise<void> {
		const key = `${KEY_PREFIX}${resourceId}`;
		await this.valkey.sadd(key, actorId);
		await this.valkey.expire(key, this.ttlSeconds);
	}

	async leave(resourceId: string, actorId: string): Promise<void> {
		await this.valkey.srem(`${KEY_PREFIX}${resourceId}`, actorId);
	}

	async peers(resourceId: string): Promise<string[]> {
		return this.valkey.smembers(`${KEY_PREFIX}${resourceId}`);
	}
}
