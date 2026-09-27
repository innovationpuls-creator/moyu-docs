/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;

/**
 * Internal Realtime query. Read the semantic projection of the latest durable Yjs Resource state, or the state at a historical Journal sequence.
 */
export interface ReadResourceContent {
	resourceId: ResourceId;
	atJournalSeq?: number;
}
