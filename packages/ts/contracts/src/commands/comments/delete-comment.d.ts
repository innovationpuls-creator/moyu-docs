/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-CMT-004. Author soft-deletes their comment (thread integrity kept).
 */
export interface DeleteComment {
	commentId: UserId;
	idempotencyKey: IdempotencyKey;
}
