import type {
	AwarenessEvent,
	AwarenessParticipant,
} from "@dom/contracts/realtime/awareness-event";
import type { AwarenessState } from "@dom/contracts/realtime/awareness-state";
import {
	decodeRealtimeBinaryFrame,
	encodeRealtimeBinaryFrame,
	type RealtimeBinaryFrame,
	type RealtimeBinaryHeader,
	type SyncMessageType,
} from "@dom/realtime-protocol";

export type {
	AwarenessEvent,
	AwarenessParticipant,
	AwarenessState,
	RealtimeBinaryFrame,
	RealtimeBinaryHeader,
	SyncMessageType,
};
export { decodeRealtimeBinaryFrame, encodeRealtimeBinaryFrame };

export const MAX_AWARENESS_OFFSET = 10_000_000;

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
