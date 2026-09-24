/**
 * RT2 — NATS broadcast relay (arch 06/25 transport style, arch 05 §6 routing).
 *
 * The gateway relays realtime broadcast envelopes from a NATS subject
 * (``rt.broadcast.>``) to connections subscribed to the contained resource
 * subject. Delivery is at-least-once and duplicate-tolerant (dispatch is
 * idempotent per envelope: same resourceId + sequence collapses in the
 * subscription manager's dispatch path).
 */

import {
	consumerOpts,
	type JetStreamClient,
	type JetStreamSubscription,
} from "nats";

interface RelayMessage {
	data: Uint8Array;
	ack(): Promise<void>;
	term(): Promise<void>;
}

export interface BroadcastEnvelope {
	resourceId: string;
	kind: string;
	payload: unknown;
	sequence?: number;
	occurredAt?: string;
}

export interface DispatchSink {
	dispatch(resourceId: string, envelope: unknown): number;
}

export class NatsBroadcastRelay {
	private readonly subject = "rt.broadcast.>";
	private sub: JetStreamSubscription | null = null;

	constructor(
		private readonly js: JetStreamClient,
		private readonly sink: DispatchSink,
	) {}

	async start(): Promise<void> {
		this.sub = await this.js.subscribe(
			this.subject,
			consumerOpts({
				durable_name: "realtime-gateway-relay",
				deliver_subject: "dom_rt_deliver_gateway",
			}),
		);
		// eslint-disable-next-line no-void
		void this.consume();
	}

	private async consume(): Promise<void> {
		for await (const raw of this.sub!) {
			const msg = raw as unknown as RelayMessage;
			this.handle(msg).catch(() => msg.term());
		}
	}

	private async handle(msg: RelayMessage): Promise<void> {
		try {
			const envelope = JSON.parse(msg.data.toString()) as BroadcastEnvelope;
			if (!envelope.resourceId) throw new Error("missing resourceId");
			this.sink.dispatch(envelope.resourceId, {
				kind: envelope.kind ?? "op",
				payload: envelope.payload,
				sequence: envelope.sequence,
				occurredAt: envelope.occurredAt ?? new Date().toISOString(),
			});
			msg.ack();
		} catch {
			// malformed or un-routable: terminate (dead-letter semantics)
			msg.term();
		}
	}

	async stop(): Promise<void> {
		await this.sub?.unsubscribe();
		this.sub = null;
	}
}
