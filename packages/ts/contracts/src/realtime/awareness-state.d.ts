/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

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
