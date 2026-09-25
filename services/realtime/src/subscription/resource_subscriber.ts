import * as Y from "yjs";
import type { PresenceStore } from "../backlog/presence_store.js";
import { MemoryPresenceStore } from "../backlog/presence_store.js";
import type { YjsBacklogStore } from "../backlog/yjs_backlog_store.js";
import { MemoryYjsBacklogStore } from "../backlog/yjs_backlog_store.js";
/**
 * RT1 — resource subject subscriptions (arch 05 §11).
 *
 * The gateway authorizes every subscription against Permission-owned resource
 * ownership via an injected callback; unauthorized subscriptions are rejected
 * with a typed result. Dispatch is subject-routed: an envelope for a resource
 * subject reaches only connections subscribed to that subject.
 */

export interface SubscriptionAuthorizer {
	authorizeResource(actorId: string, resourceId: string): Promise<boolean>;
	authorizeResourceUpdate(
		actorId: string,
		resourceId: string,
	): Promise<boolean>;
}

export interface OutboundSender {
	send(connectionId: string, envelope: unknown): void;
}

export interface OpEnvelope {
	subject: string;
	resourceId: string;
	subscriptionId?: string;
	kind: "op" | "presence" | "subscribe" | "unsubscribe";
	payload: unknown;
	occurredAt?: string;
}

export const SUBSCRIPTION_DENIED = "denied";
export const SUBSCRIPTION_OK = "ok";

export class ResourceSubscriptionManager {
	private readonly subscriptions = new Map<string, Set<string>>(); // conn -> subjects
	private readonly bySubject = new Map<string, Set<string>>(); // subject -> conns
	private readonly actors = new Map<string, string>(); // conn -> actor
	private readonly subscriptionIds = new Map<string, string>(); // conn + resource -> subscription

	constructor(
		private readonly authorize: SubscriptionAuthorizer,
		private readonly sender: OutboundSender,
		private readonly backlogStore?: YjsBacklogStore,
		private readonly presence?: PresenceStore,
	) {
		this.backlogStore ??= new MemoryYjsBacklogStore();
		this.presence ??= new MemoryPresenceStore();
	}

	async subscribe(
		connectionId: string,
		actorId: string,
		resourceId: string,
		subscriptionId = "",
	): Promise<"ok" | "denied"> {
		if (!(await this.authorize.authorizeResource(actorId, resourceId))) {
			return SUBSCRIPTION_DENIED;
		}
		const subject = subjectFor(resourceId);
		let connSubjects = this.subscriptions.get(connectionId);
		if (!connSubjects) {
			connSubjects = new Set<string>();
			this.subscriptions.set(connectionId, connSubjects);
		}
		connSubjects.add(subject);
		let conns = this.bySubject.get(subject);
		if (!conns) {
			conns = new Set<string>();
			this.bySubject.set(subject, conns);
		}
		conns.add(connectionId);
		this.subscriptionIds.set(
			subscriptionKey(connectionId, resourceId),
			subscriptionId,
		);
		this.sender.send(connectionId, {
			subject,
			resourceId,
			subscriptionId,
			kind: "subscribe",
			payload: { status: "ok" },
		});
		this.broadcastRoster(subject, resourceId);
		this.sendBacklog(subject, resourceId, connectionId);
		this.actors.set(connectionId, actorId);
		void this.presence?.join(resourceId, actorId);
		return SUBSCRIPTION_OK;
	}

	/** Roster presence (arch 05): every subscribe/leave pushes the peer count. */
	private broadcastRoster(subject: string, resourceId: string): void {
		const conns = this.bySubject.get(subject);
		const peers = conns?.size ?? 0;
		for (const connectionId of conns ?? []) {
			this.sender.send(connectionId, {
				subject,
				resourceId,
				subscriptionId: this.getSubscriptionId(connectionId, resourceId),
				kind: "op",
				payload: { kind: "roster", peers },
				occurredAt: new Date().toISOString(),
			});
		}
	}

	isSubscribed(
		connectionId: string,
		resourceId: string,
		subscriptionId?: string,
	): boolean {
		const subject = subjectFor(resourceId);
		if (!(this.subscriptions.get(connectionId)?.has(subject) ?? false))
			return false;
		return (
			subscriptionId === undefined ||
			this.getSubscriptionId(connectionId, resourceId) === subscriptionId
		);
	}

	getSubscriptionId(connectionId: string, resourceId: string): string {
		return (
			this.subscriptionIds.get(subscriptionKey(connectionId, resourceId)) ?? ""
		);
	}

	/** Yjs update backlog (arch 05 §initial sync): bounded per subject; late
	 * joiners replay it for catch-up (durable cross-restart storage deferred). */
	recordYjsUpdate(resourceId: string, updateBase64: string): void {
		void this.backlogStore?.record(resourceId, updateBase64);
	}

	/** Validate the current session's write capability before persisting or
	 * broadcasting a client-originated Yjs update. Read subscriptions remain
	 * active for receiving updates; only this publish path requires write access. */
	async publishYjsUpdate(
		connectionId: string,
		resourceId: string,
		subscriptionId: string,
		updateBase64: string,
	): Promise<boolean> {
		const actorId = this.actors.get(connectionId);
		if (
			!actorId ||
			!this.isSubscribed(connectionId, resourceId, subscriptionId)
		) {
			return false;
		}

		let mayUpdate = false;
		try {
			mayUpdate = await this.authorize.authorizeResourceUpdate(
				actorId,
				resourceId,
			);
		} catch {
			// Fail closed when the authoritative capability check is unavailable.
			return false;
		}
		if (
			!mayUpdate ||
			this.actors.get(connectionId) !== actorId ||
			!this.isSubscribed(connectionId, resourceId, subscriptionId)
		) {
			return false;
		}

		await this.backlogStore?.record(resourceId, updateBase64);
		this.dispatch(
			resourceId,
			{ kind: "op", payload: { kind: "yjs", update: updateBase64 } },
			connectionId,
		);
		return true;
	}

	/** arch 05 incremental sync: merge the backlog updates, diff against the
	 * requester's state-vector, deliver exactly the missing tail once. */
	async incrementalSync(
		connectionId: string,
		resourceId: string,
		vectorBase64: string,
	): Promise<void> {
		const store = this.backlogStore ?? new MemoryYjsBacklogStore();
		const updates = await store.recent(resourceId);
		if (updates.length === 0) return;
		const merged = new Y.Doc();
		for (const update of updates) {
			Y.applyUpdate(
				merged,
				Uint8Array.from(atob(update), (c) => c.charCodeAt(0)),
			);
		}
		const vector = Uint8Array.from(atob(vectorBase64), (c) => c.charCodeAt(0));
		const tail = Y.encodeStateAsUpdate(merged, vector);
		const subject = subjectFor(resourceId);
		this.sender.send(connectionId, {
			subject,
			resourceId,
			subscriptionId: this.getSubscriptionId(connectionId, resourceId),
			kind: "op",
			payload: { kind: "yjs", update: btoa(String.fromCharCode(...tail)) },
			occurredAt: new Date().toISOString(),
		});
	}

	private sendBacklog(subject: string, resourceId: string, to: string): void {
		void this.backlogStore?.recent(resourceId).then((updates) => {
			for (const update of updates) {
				this.sender.send(to, {
					subject,
					resourceId,
					subscriptionId: this.getSubscriptionId(to, resourceId),
					kind: "op",
					payload: { kind: "yjs", update },
					occurredAt: new Date().toISOString(),
				});
			}
		});
	}

	unsubscribe(
		connectionId: string,
		resourceId: string,
		subscriptionId?: string,
	): void {
		if (
			subscriptionId !== undefined &&
			this.getSubscriptionId(connectionId, resourceId) !== subscriptionId
		) {
			return;
		}
		const subject = subjectFor(resourceId);
		const connSubjects = this.subscriptions.get(connectionId);
		if (connSubjects) {
			connSubjects.delete(subject);
			if (connSubjects.size === 0) {
				this.subscriptions.delete(connectionId);
			}
		}
		this.bySubject.get(subject)?.delete(connectionId);
		this.subscriptionIds.delete(subscriptionKey(connectionId, resourceId));
	}

	dropConnection(connectionId: string): void {
		const subjects = this.subscriptions.get(connectionId);
		const actorId = this.actors.get(connectionId);
		if (!subjects) return;
		for (const subject of subjects) {
			this.bySubject.get(subject)?.delete(connectionId);
			const resourceId = subject.replace(/^rt\.resource\./, "");
			this.subscriptionIds.delete(subscriptionKey(connectionId, resourceId));
			if (actorId) void this.presence?.leave(resourceId, actorId);
			this.broadcastRoster(subject, resourceId);
		}
		this.subscriptions.delete(connectionId);
		this.actors.delete(connectionId);
	}

	dispatch(
		resourceId: string,
		envelope: Omit<OpEnvelope, "subject" | "resourceId">,
		exceptConnectionId?: string,
	): number {
		const subject = subjectFor(resourceId);
		const conns = this.bySubject.get(subject);
		if (!conns) return 0;
		const message: OpEnvelope = {
			subject,
			resourceId,
			...envelope,
			occurredAt: envelope.occurredAt ?? new Date().toISOString(),
		};
		let sent = 0;
		for (const connectionId of conns) {
			if (connectionId === exceptConnectionId) continue;
			this.sender.send(connectionId, {
				...message,
				subscriptionId: this.getSubscriptionId(connectionId, resourceId),
			});
			sent += 1;
		}
		return sent;
	}
}

export function subjectFor(resourceId: string): string {
	return `rt.resource.${resourceId}`;
}

function subscriptionKey(connectionId: string, resourceId: string): string {
	return `${connectionId}\u0000${resourceId}`;
}
