/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type CommentId = string;
export type IdempotencyKey = string;

/**
 * FR-CMT-003. Author edits their own comment body.
 */
export interface EditComment {
	commentId: CommentId;
	body: string;
	idempotencyKey: IdempotencyKey;
}
