/**
 * Gateway relay host: bridges the NATS broadcast relay into per-connection
 * resource subscriptions (arch 05 §11/§6 routing).
 *
 * One ResourceSubscriptionManager per server; connections register under an
 * opaque connection id; the NATS relay's sink dispatches envelopes to the
 * manager, which routes them to exactly the connections subscribed to the
 * contained resource subject.
 */

import { connect, type JetStreamClient } from "nats";
import type { PresenceStore } from "../backlog/presence_store.js";
import type { YjsBacklogStore } from "../backlog/yjs_backlog_store.js";
import {
	type OpEnvelope,
	ResourceSubscriptionManager,
} from "../subscription/resource_subscriber.js";

import { NatsBroadcastRelay } from "./nats_broadcast_relay.js";

export interface RelayHostOptions {
	/** API base used for read and write capability checks; default deny on
	 * network errors. */
	apiBaseUrl: string;
	natsUrl: string;
	/** Yjs backlog store for late-join catch-up (arch 05); default in-memory. */
	backlogStore?: YjsBacklogStore;
	/** Presence roster store (arch 05); default in-memory. */
	presenceStore?: PresenceStore;
}

export interface ConnectionRegistry {
	add(connectionId: string, send: (envelope: unknown) => void): void;
	remove(connectionId: string): void;
}

export class GatewayRelayHost {
	readonly manager: ResourceSubscriptionManager;
	private readonly connections = new Map<string, (envelope: unknown) => void>();
	private relay: NatsBroadcastRelay | null = null;

	constructor(private readonly options: RelayHostOptions) {
		this.manager = new ResourceSubscriptionManager(
			{
				authorizeResource: async (actorId, resourceId) =>
					this.authorize(actorId, resourceId),
				authorizeResourceUpdate: async (actorId, resourceId) =>
					this.authorizeUpdate(actorId, resourceId),
			},
			{
				send: (connectionId, envelope) => {
					this.connections.get(connectionId)?.(envelope);
				},
			},
			this.options.backlogStore,
			this.options.presenceStore,
		);
	}

	private async authorize(
		actorId: string,
		resourceId: string,
	): Promise<boolean> {
		try {
			const response = await fetch(
				`${this.options.apiBaseUrl}/v1/resources/${resourceId}`,
				{ headers: { cookie: `dom_session=${actorId}` } },
			);
			if (response.status !== 200) {
				console.error(
					"[dom/realtime] subscribe authorize refused",
					resourceId,
					response.status,
				);
			}
			return response.status === 200;
		} catch {
			// Default deny: authorization must never fail open.
			return false;
		}
	}

	private async authorizeUpdate(
		actorId: string,
		resourceId: string,
	): Promise<boolean> {
		try {
			const response = await fetch(
				`${this.options.apiBaseUrl}/v1/resources/${encodeURIComponent(resourceId)}/capabilities`,
				{
					headers: { cookie: `dom_session=${actorId}` },
					signal: AbortSignal.timeout(3000),
				},
			);
			if (response.status !== 200) return false;
			const capabilities: unknown = await response.json();
			return (
				typeof capabilities === "object" &&
				capabilities !== null &&
				"resourceId" in capabilities &&
				capabilities.resourceId === resourceId &&
				"canUpdate" in capabilities &&
				capabilities.canUpdate === true
			);
		} catch {
			// Capability lookup failures deny this update; no positive result is cached.
			return false;
		}
	}

	/** One connection's lifecycle hook (called by the gateway). */
	async registerConnection(
		connectionId: string,
		send: (envelope: unknown) => void,
	): Promise<void> {
		this.connections.set(connectionId, send);
	}

	unregisterConnection(connectionId: string): void {
		this.connections.delete(connectionId);
		this.manager.dropConnection(connectionId);
	}

	async startRelay(tries = 8, delayMs = 500): Promise<void> {
		let nc: Awaited<ReturnType<typeof connect>> | null = null;
		for (let attempt = 0; attempt < tries; attempt += 1) {
			try {
				nc = await connect({ servers: this.options.natsUrl });
				break;
			} catch (error) {
				if (attempt === tries - 1) throw error;
				// NATS may still be provisioning at gateway boot: retry with
				// backoff instead of failing the relay permanently.
				await new Promise((resolve) => setTimeout(resolve, delayMs));
			}
		}
		if (nc === null) throw new Error("nats connection unavailable");
		const js: JetStreamClient = nc.jetstream();
		this.relay = new NatsBroadcastRelay(js, {
			dispatch: (resourceId, envelope) => {
				console.error("[dom/realtime] relay dispatch", resourceId);
				return this.manager.dispatch(
					resourceId,
					envelope as Omit<OpEnvelope, "subject" | "resourceId">,
				);
			},
		});
		// Provision the broadcast stream idempotently (captures core publishes).
		const jsm = await nc.jetstreamManager();
		const streams = await jsm.streams
			.info("DOM_REALTIME_BROADCAST")
			.catch(() => null);
		if (streams === null) {
			await jsm.streams.add({
				name: "DOM_REALTIME_BROADCAST",
				subjects: ["rt.broadcast.>"],
			});
		}
		await this.relay.start();
	}

	async stopRelay(): Promise<void> {
		await this.relay?.stop();
		this.relay = null;
	}
}
