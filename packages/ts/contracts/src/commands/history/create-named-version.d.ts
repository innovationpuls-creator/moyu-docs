/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-HS-003. Label a revision for later restore.
 */
export interface CreateNamedVersion {
	resourceId: UserId;
	label: string;
	baseJournalSeq: number;
	idempotencyKey: IdempotencyKey;
}
