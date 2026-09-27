import type { ReplaceResourceContent } from "@dom/contracts/commands/resource/replace-resource-content";
import type { ReadResourceContent } from "@dom/contracts/queries/resource/read-resource-content";
import type { NatsConnection, Subscription } from "nats";
import {
	type PostgresResourceContentService,
	ResourceContentError,
} from "./resource_content.js";

const READ_SUBJECT = "dom.resource.content.read.v1";
const REPLACE_SUBJECT = "dom.resource.content.replace.v1";

export class ResourceContentCommandServer {
	private readonly subscriptions: Subscription[] = [];

	constructor(
		private readonly connection: NatsConnection,
		private readonly content: PostgresResourceContentService,
	) {}

	start(): void {
		const read = this.connection.subscribe(READ_SUBJECT, {
			queue: "realtime-resource-content",
		});
		const replace = this.connection.subscribe(REPLACE_SUBJECT, {
			queue: "realtime-resource-content",
		});
		this.subscriptions.push(read, replace);
		void this.consume(read, (data) => this.read(data));
		void this.consume(replace, (data) => this.replace(data));
	}

	async stop(): Promise<void> {
		for (const subscription of this.subscriptions) {
			subscription.unsubscribe();
		}
		this.subscriptions.length = 0;
	}

	private async consume(
		subscription: Subscription,
		handle: (request: unknown) => Promise<unknown>,
	): Promise<void> {
		for await (const message of subscription) {
			try {
				const request = JSON.parse(message.data.toString()) as unknown;
				const response = await handle(request);
				message.respond(JSON.stringify(response));
			} catch (error) {
				const failure = toErrorResponse(error);
				message.respond(JSON.stringify(failure));
			}
		}
	}

	private async read(request: unknown): Promise<unknown> {
		if (!isRecord(request) || !isUuid(request.resourceId)) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"resourceId is invalid",
			);
		}
		const atJournalSeq = request.atJournalSeq;
		if (
			atJournalSeq !== undefined &&
			(!Number.isSafeInteger(atJournalSeq) || Number(atJournalSeq) < 0)
		) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"atJournalSeq is invalid",
			);
		}
		return this.content.read({
			resourceId: request.resourceId,
			...(atJournalSeq === undefined
				? {}
				: { atJournalSeq: Number(atJournalSeq) }),
		} satisfies ReadResourceContent);
	}

	private async replace(request: unknown): Promise<unknown> {
		if (
			!isRecord(request) ||
			!isUuid(request.resourceId) ||
			!isUuid(request.operationId) ||
			!(request.createdBy === null || isUuid(request.createdBy)) ||
			(request.reason !== "import" &&
				request.reason !== "history-restore" &&
				request.reason !== "ai-changeset") ||
			!isRecord(request.snapshot)
		) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"ReplaceResourceContent request is invalid",
			);
		}
		const expectedJournalSeq = request.expectedJournalSeq;
		const restoreTargetSeq = request.restoreTargetSeq;
		if (
			(expectedJournalSeq !== undefined &&
				(!Number.isSafeInteger(expectedJournalSeq) ||
					Number(expectedJournalSeq) < 0)) ||
			(restoreTargetSeq !== undefined &&
				(!Number.isSafeInteger(restoreTargetSeq) ||
					Number(restoreTargetSeq) < 1))
		) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"ReplaceResourceContent sequence is invalid",
			);
		}
		const result = await this.content.replace({
			resourceId: request.resourceId,
			operationId: request.operationId,
			createdBy: request.createdBy,
			reason: request.reason,
			snapshot:
				request.snapshot as unknown as ReplaceResourceContent["snapshot"],
			...(expectedJournalSeq === undefined
				? {}
				: { expectedJournalSeq: Number(expectedJournalSeq) }),
			...(restoreTargetSeq === undefined
				? {}
				: { restoreTargetSeq: Number(restoreTargetSeq) }),
		});
		const envelope = {
			resourceId: request.resourceId,
			kind: "op",
			payload: {
				kind: "yjs",
				update: Buffer.from(result.update).toString("base64"),
				journalSeq: result.broadcastJournalSeq,
			},
			sequence: result.broadcastJournalSeq,
			occurredAt: new Date().toISOString(),
			schemaVersion: "1.0.0",
		};
		await this.connection.publish(
			`rt.broadcast.${request.resourceId}`,
			JSON.stringify(envelope),
		);
		await this.connection.flush();
		return {
			resourceId: request.resourceId,
			journalSeq: result.journalSeq,
		};
	}
}

function toErrorResponse(error: unknown): {
	error: { code: string; message: string; nextJournalSeq?: number };
} {
	if (error instanceof ResourceContentError) {
		return {
			error: {
				code: error.code,
				message: error.message,
				...(error.nextJournalSeq === undefined
					? {}
					: { nextJournalSeq: error.nextJournalSeq }),
			},
		};
	}
	console.error("[dom/realtime] resource content command failed", error);
	return {
		error: {
			code: "RESOURCE_CONTENT_UNAVAILABLE",
			message: "Realtime could not complete the Resource content command",
		},
	};
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isUuid(value: unknown): value is string {
	return (
		typeof value === "string" &&
		/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(
			value,
		)
	);
}
