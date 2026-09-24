/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-RC-002. Append one content op to a Resource's journal (authorized by ownership). The op is sha256 of the transported update; client provides expectedSeq to make concurrency explicit.
 */
export interface AppendJournalOp {
	resourceId: UserId;
	expectedSeq?: number;
	update: string;
	idempotencyKey: IdempotencyKey;
}
