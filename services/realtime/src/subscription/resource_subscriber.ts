import { randomUUID } from "node:crypto";
import type { CommentRealtimeEvent } from "@dom/contracts/realtime/comment-event";
import * as Y from "yjs";
import type { PresenceStore } from "../backlog/presence_store.js";
import { MemoryPresenceStore } from "../backlog/presence_store.js";
import type { YjsBacklogStore } from "../backlog/yjs_backlog_store.js";
import { MemoryYjsBacklogStore } from "../backlog/yjs_backlog_store.js";
import {
	type AwarenessEvent,
	type AwarenessParticipant,
	type AwarenessState,
	parseAwarenessState,
} from "../protocol/realtime_frame.js";
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
	kind:
		| "op"
		| "presence"
		| "subscribe"
		| "unsubscribe"
		| CommentRealtimeEvent["kind"];
	payload: unknown;
	occurredAt?: string;
}

export interface AuthenticatedPresenceIdentity {
	accountId: string;
}

interface PresenceRecord {
	connectionId: string;
	resourceId: string;
	participant: AwarenessParticipant;
	state: AwarenessState;
	lastSentAt: number;
	timer: ReturnType<typeof setTimeout> | null;
}

const AWARENESS_THROTTLE_MS = 80;
const PARTICIPANT_COLORS = [
	"#2563eb",
	"#9333ea",
	"#db2777",
	"#ea580c",
	"#059669",
	"#0891b2",
] as const;

export const SUBSCRIPTION_DENIED = "denied";
export const SUBSCRIPTION_OK = "ok";

export class ResourceSubscriptionManager {
	private readonly subscriptions = new Map<string, Set<string>>(); // conn -> subjects
	private readonly bySubject = new Map<string, Set<string>>(); // subject -> conns
	private readonly actors = new Map<string, string>(); // conn -> actor
	private readonly subscriptionIds = new Map<string, string>(); // conn + resource -> subscription
	private readonly participants = new Map<string, PresenceRecord>(); // conn + resource -> ephemeral presence
	private readonly participantsByResource = new Map<
		string,
		Map<string, PresenceRecord>
	>();

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
		presenceIdentity?: AuthenticatedPresenceIdentity,
	): Promise<"ok" | "denied"> {
		if (!(await this.authorize.authorizeResource(actorId, resourceId))) {
			return SUBSCRIPTION_DENIED;
		}
		if (this.isSubscribed(connectionId, resourceId)) {
			this.unsubscribe(connectionId, resourceId);
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
		this.actors.set(connectionId, actorId);
		if (presenceIdentity?.accountId) {
			this.addParticipant(connectionId, resourceId, presenceIdentity.accountId);
		}
		this.sender.send(connectionId, {
			subject,
			resourceId,
			subscriptionId,
			kind: "subscribe",
			payload: { status: "ok" },
		});
		this.broadcastRoster(subject, resourceId);
		this.sendPresenceSnapshot(connectionId, resourceId);
		const ownPresence = this.participants.get(
			subscriptionKey(connectionId, resourceId),
		);
		if (ownPresence) this.broadcastPresence(ownPresence, connectionId);
		this.sendBacklog(subject, resourceId, connectionId);
		void this.presence?.join(resourceId, actorId);
		return SUBSCRIPTION_OK;
	}

	private addParticipant(
		connectionId: string,
		resourceId: string,
		accountId: string,
	): void {
		const compactId = accountId.replaceAll("-", "");
		const participant: AwarenessParticipant = {
			participantId: randomUUID(),
			displayName: `协作者-${compactId.slice(-4).toUpperCase()}`,
			color: stableParticipantColor(accountId),
		};
		const record: PresenceRecord = {
			connectionId,
			resourceId,
			participant,
			state: { cursor: null },
			lastSentAt: Number.NEGATIVE_INFINITY,
			timer: null,
		};
		this.participants.set(subscriptionKey(connectionId, resourceId), record);
		const room = this.participantsByResource.get(resourceId) ?? new Map();
		room.set(participant.participantId, record);
		this.participantsByResource.set(resourceId, room);
	}

	private sendPresenceSnapshot(connectionId: string, resourceId: string): void {
		for (const record of this.participantsByResource
			.get(resourceId)
			?.values() ?? []) {
			if (record.connectionId === connectionId) continue;
			this.sendAwarenessEvent(connectionId, resourceId, {
				kind: "update",
				participant: record.participant,
				state: record.state,
			});
		}
	}

	private sendAwarenessEvent(
		connectionId: string,
		resourceId: string,
		event: AwarenessEvent,
	): void {
		this.sender.send(connectionId, {
			subject: subjectFor(resourceId),
			resourceId,
			subscriptionId: this.getSubscriptionId(connectionId, resourceId),
			kind: "op",
			payload: { kind: "awareness", event },
			occurredAt: new Date().toISOString(),
		});
	}

	private broadcastPresence(
		record: PresenceRecord,
		exceptConnectionId?: string,
	): void {
		const event: AwarenessEvent = {
			kind: "update",
			participant: record.participant,
			state: record.state,
		};
		for (const connectionId of this.bySubject.get(
			subjectFor(record.resourceId),
		) ?? []) {
			if (connectionId === exceptConnectionId) continue;
			this.sendAwarenessEvent(connectionId, record.resourceId, event);
		}
	}

	/** Only a current, authorized Resource subscription can publish ephemeral cursor state. */
	publishAwareness(
		connectionId: string,
		resourceId: string,
		subscriptionId: string,
		state: unknown,
	): boolean {
		if (!this.isSubscribed(connectionId, resourceId, subscriptionId))
			return false;
		const record = this.participants.get(
			subscriptionKey(connectionId, resourceId),
		);
		const parsed = parseAwarenessState(state);
		if (!record || parsed === null) return false;
		record.state = parsed;
		const waitMs = AWARENESS_THROTTLE_MS - (Date.now() - record.lastSentAt);
		if (waitMs <= 0) {
			this.flushPresence(record);
		} else if (record.timer === null) {
			record.timer = setTimeout(() => {
				record.timer = null;
				if (
					this.participants.get(subscriptionKey(connectionId, resourceId)) ===
					record
				) {
					this.flushPresence(record);
				}
			}, waitMs);
		}
		return true;
	}

	private flushPresence(record: PresenceRecord): void {
		record.lastSentAt = Date.now();
		this.broadcastPresence(record, record.connectionId);
	}

	private removeParticipant(connectionId: string, resourceId: string): void {
		const key = subscriptionKey(connectionId, resourceId);
		const record = this.participants.get(key);
		if (!record) return;
		if (record.timer !== null) clearTimeout(record.timer);
		this.participants.delete(key);
		const room = this.participantsByResource.get(resourceId);
		room?.delete(record.participant.participantId);
		if (room?.size === 0) this.participantsByResource.delete(resourceId);
		const event: AwarenessEvent = {
			kind: "remove",
			participantId: record.participant.participantId,
		};
		for (const peer of this.bySubject.get(subjectFor(resourceId)) ?? []) {
			if (peer === connectionId) continue;
			this.sendAwarenessEvent(peer, resourceId, event);
		}
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

	/** Revalidate edit capability for this Session and Subscription before the
	 * update becomes visible or enters the reconnect backlog. Read-only peers
	 * keep their subscription and can continue receiving updates. */
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

		let canUpdate = false;
		try {
			canUpdate = await this.authorize.authorizeResourceUpdate(
				actorId,
				resourceId,
			);
		} catch {
			return false;
		}

		// Permission lookup is asynchronous; do not let a result for a stale or
		// replaced subscription authorize a delayed frame.
		if (
			!canUpdate ||
			this.actors.get(connectionId) !== actorId ||
			!this.isSubscribed(connectionId, resourceId, subscriptionId)
		) {
			return false;
		}

		this.recordYjsUpdate(resourceId, updateBase64);
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
		this.removeParticipant(connectionId, resourceId);
		this.bySubject.get(subject)?.delete(connectionId);
		if (this.bySubject.get(subject)?.size === 0) this.bySubject.delete(subject);
		this.subscriptionIds.delete(subscriptionKey(connectionId, resourceId));
		const actorId = this.actors.get(connectionId);
		if (actorId) void this.presence?.leave(resourceId, actorId);
		if ((this.subscriptions.get(connectionId)?.size ?? 0) === 0) {
			this.actors.delete(connectionId);
		}
		this.broadcastRoster(subject, resourceId);
	}

	dropConnection(connectionId: string): void {
		const subjects = this.subscriptions.get(connectionId);
		const actorId = this.actors.get(connectionId);
		for (const subject of subjects ?? []) {
			const resourceId = subject.replace(/^rt\.resource\./, "");
			this.removeParticipant(connectionId, resourceId);
			this.bySubject.get(subject)?.delete(connectionId);
			if (this.bySubject.get(subject)?.size === 0)
				this.bySubject.delete(subject);
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

function stableParticipantColor(accountId: string): string {
	let hash = 2166136261;
	for (const character of accountId.toLowerCase()) {
		hash ^= character.charCodeAt(0);
		hash = Math.imul(hash, 16777619);
	}
	return PARTICIPANT_COLORS[(hash >>> 0) % PARTICIPANT_COLORS.length];
}
