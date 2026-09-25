const MAGIC = new Uint8Array([0x44, 0x4d]);
const HEADER_SIZE = 6;
const PROTOCOL_VERSION = 1;

import type {
	AwarenessEvent,
	AwarenessParticipant,
} from "@dom/contracts/realtime/awareness-event";
import type { AwarenessState } from "@dom/contracts/realtime/awareness-state";
import type { CommentRealtimeEvent } from "@dom/contracts/realtime/comment-event";
import type {
	RealtimeSyncFrameHeader,
	RealtimeSyncMessageType,
} from "@dom/contracts/realtime/frame-header";

export type {
	AwarenessEvent,
	AwarenessParticipant,
	AwarenessState,
	CommentRealtimeEvent,
};
export type SyncMessageType = RealtimeSyncMessageType;

export const MAX_AWARENESS_OFFSET = 10_000_000;

export type RealtimeBinaryHeader = RealtimeSyncFrameHeader;

export interface RealtimeBinaryFrame {
	header: RealtimeBinaryHeader;
	payload: Uint8Array;
}

/** Reject extra identity fields: a browser may submit cursor positions only. */
export function parseAwarenessState(value: unknown): AwarenessState | null {
	if (!isRecord(value) || !hasExactKeys(value, ["cursor"])) return null;
	if (value.cursor === null) return { cursor: null };
	if (
		!isRecord(value.cursor) ||
		!hasExactKeys(value.cursor, ["anchor", "head"])
	)
		return null;
	const { anchor, head } = value.cursor;
	if (!isValidOffset(anchor) || !isValidOffset(head)) return null;
	return { cursor: { anchor, head } };
}

/** Validate server-to-client Awareness frames before exposing them to a Feature. */
export function parseAwarenessEvent(value: unknown): AwarenessEvent | null {
	if (!isRecord(value)) return null;
	if (value.kind === "remove") {
		return typeof value.participantId === "string" &&
			value.participantId.length > 0
			? { kind: "remove", participantId: value.participantId }
			: null;
	}
	if (value.kind !== "update" || !isRecord(value.participant)) return null;
	const participant = value.participant;
	if (
		typeof participant.participantId !== "string" ||
		participant.participantId.length === 0 ||
		typeof participant.displayName !== "string" ||
		participant.displayName.length === 0 ||
		typeof participant.color !== "string" ||
		!/^#[0-9a-fA-F]{6}$/.test(participant.color)
	) {
		return null;
	}
	const state = parseAwarenessState(value.state);
	return state === null
		? null
		: {
				kind: "update",
				participant: {
					participantId: participant.participantId,
					displayName: participant.displayName,
					color: participant.color,
				},
				state,
			};
}

const COMMENT_EVENT_KINDS = [
	"comment.added",
	"comment.edited",
	"comment.deleted",
	"ThreadResolved",
	"ThreadReopened",
] as const;

export function isCommentRealtimeEventKind(
	value: unknown,
): value is (typeof COMMENT_EVENT_KINDS)[number] {
	return (
		typeof value === "string" &&
		COMMENT_EVENT_KINDS.includes(value as (typeof COMMENT_EVENT_KINDS)[number])
	);
}

/** Validate Resource-scoped comment events before exposing them to features. */
export function parseCommentRealtimeEvent(
	value: unknown,
): CommentRealtimeEvent | null {
	if (!isRecord(value) || !isUuid(value.resourceId)) return null;
	if (
		value.protocolVersion !== 1 ||
		!isUuid(value.subscriptionId) ||
		value.subject !== `rt.resource.${value.resourceId}` ||
		!isCommentRealtimeEventKind(value.kind) ||
		typeof value.occurredAt !== "string" ||
		!Number.isFinite(Date.parse(value.occurredAt)) ||
		!isRecord(value.payload)
	) {
		return null;
	}
	if (
		value.sequence !== undefined &&
		value.sequence !== null &&
		(!Number.isSafeInteger(value.sequence) || (value.sequence as number) < 0)
	) {
		return null;
	}

	const payload = value.payload;
	switch (value.kind) {
		case "comment.added":
			if (
				!isUuid(payload.resourceId) ||
				!isUuid(payload.commentId) ||
				!isUuid(payload.threadId) ||
				!isUuid(payload.author) ||
				typeof payload.body !== "string" ||
				payload.body.length === 0 ||
				payload.resourceId !== value.resourceId ||
				!hasExactKeys(payload, [
					"resourceId",
					"commentId",
					"threadId",
					"author",
					"body",
				])
			) {
				return null;
			}
			break;
		case "comment.edited":
			if (
				!isUuid(payload.commentId) ||
				typeof payload.body !== "string" ||
				payload.body.length === 0 ||
				!hasExactKeys(payload, ["commentId", "body"])
			) {
				return null;
			}
			break;
		case "comment.deleted":
			if (!isUuid(payload.commentId) || !hasExactKeys(payload, ["commentId"])) {
				return null;
			}
			break;
		case "ThreadResolved":
			if (!isThreadTransitionPayload(payload, value.resourceId, "Resolved"))
				return null;
			break;
		case "ThreadReopened":
			if (!isThreadTransitionPayload(payload, value.resourceId, "Open"))
				return null;
			break;
	}
	if (
		!hasExactKeys(value, [
			"protocolVersion",
			"subject",
			"resourceId",
			"subscriptionId",
			"kind",
			"payload",
			"occurredAt",
		]) &&
		!hasExactKeys(value, [
			"protocolVersion",
			"subject",
			"resourceId",
			"subscriptionId",
			"kind",
			"payload",
			"sequence",
			"occurredAt",
		])
	) {
		return null;
	}
	return value as unknown as CommentRealtimeEvent;
}

function isThreadTransitionPayload(
	value: Record<string, unknown>,
	resourceId: string,
	status: "Open" | "Resolved",
): boolean {
	return (
		isUuid(value.threadId) &&
		value.resourceId === resourceId &&
		value.status === status &&
		(value.resolvedBy === null || isUuid(value.resolvedBy)) &&
		(value.resolvedAt === null ||
			(typeof value.resolvedAt === "string" &&
				Number.isFinite(Date.parse(value.resolvedAt)))) &&
		hasExactKeys(value, [
			"threadId",
			"resourceId",
			"status",
			"resolvedBy",
			"resolvedAt",
		])
	);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
	value: Record<string, unknown>,
	keys: readonly string[],
): boolean {
	const actual = Object.keys(value);
	return actual.length === keys.length && keys.every((key) => key in value);
}

function isValidOffset(value: unknown): value is number {
	return (
		typeof value === "number" &&
		Number.isSafeInteger(value) &&
		value >= 0 &&
		value <= MAX_AWARENESS_OFFSET
	);
}

function isUuid(value: unknown): value is string {
	return (
		typeof value === "string" &&
		/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
			value,
		)
	);
}

export function encodeRealtimeBinaryFrame(
	header: Pick<
		RealtimeSyncFrameHeader,
		"messageType" | "resourceId" | "subscriptionId"
	>,
	payload: Uint8Array,
): Uint8Array {
	const fullHeader: RealtimeBinaryHeader = {
		protocolVersion: PROTOCOL_VERSION,
		frameType: "Sync",
		payloadKind: "binary",
		...header,
	};
	const headerBytes = new TextEncoder().encode(JSON.stringify(fullHeader));
	if (headerBytes.byteLength > 65_535) {
		throw new RangeError("Realtime frame header is too large");
	}
	const frame = new Uint8Array(
		HEADER_SIZE + headerBytes.byteLength + payload.byteLength,
	);
	frame.set(MAGIC, 0);
	frame[2] = PROTOCOL_VERSION;
	frame[3] = header.messageType === "sync.update" ? 1 : 2;
	new DataView(frame.buffer).setUint16(4, headerBytes.byteLength, false);
	frame.set(headerBytes, HEADER_SIZE);
	frame.set(payload, HEADER_SIZE + headerBytes.byteLength);
	return frame;
}

export function decodeRealtimeBinaryFrame(
	input: ArrayBuffer | Uint8Array,
): RealtimeBinaryFrame {
	const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
	if (
		bytes.byteLength < HEADER_SIZE ||
		bytes[0] !== MAGIC[0] ||
		bytes[1] !== MAGIC[1]
	) {
		throw new TypeError("Invalid realtime binary frame magic");
	}
	if (bytes[2] !== PROTOCOL_VERSION) {
		throw new TypeError(`Unsupported realtime protocol version ${bytes[2]}`);
	}
	const headerLength = new DataView(
		bytes.buffer,
		bytes.byteOffset,
		bytes.byteLength,
	).getUint16(4, false);
	const payloadOffset = HEADER_SIZE + headerLength;
	if (payloadOffset > bytes.byteLength) {
		throw new TypeError("Realtime frame header is truncated");
	}
	const raw = JSON.parse(
		new TextDecoder().decode(bytes.subarray(HEADER_SIZE, payloadOffset)),
	) as Partial<RealtimeBinaryHeader>;
	const messageType =
		bytes[3] === 1
			? "sync.update"
			: bytes[3] === 2
				? "sync.state-vector"
				: null;
	if (
		messageType === null ||
		raw.protocolVersion !== PROTOCOL_VERSION ||
		raw.frameType !== "Sync" ||
		raw.payloadKind !== "binary" ||
		raw.messageType !== messageType ||
		typeof raw.resourceId !== "string" ||
		typeof raw.subscriptionId !== "string"
	) {
		throw new TypeError("Realtime frame header is invalid");
	}
	return {
		header: raw as RealtimeBinaryHeader,
		payload: bytes.slice(payloadOffset),
	};
}
