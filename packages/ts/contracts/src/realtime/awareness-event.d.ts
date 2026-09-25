/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * Ephemeral, lossy Resource Awareness update or participant removal. It is not persisted as document content.
 */
export type AwarenessEvent = AwarenessUpdate | AwarenessRemove;

export interface AwarenessUpdate {
	kind: "update";
	participant: AwarenessParticipant;
	state: AwarenessState;
}
/**
 * Server-owned identity and presentation metadata attached to an Awareness update.
 */
export interface AwarenessParticipant {
	participantId: string;
	displayName: string;
	color: string;
}
/**
 * Ephemeral client Awareness input for one Resource. Identity and presentation fields are server-owned.
 */
export interface AwarenessState {
	cursor: CursorSelection | null;
}
export interface CursorSelection {
	anchor: number;
	head: number;
}
export interface AwarenessRemove {
	kind: "remove";
	participantId: string;
}
