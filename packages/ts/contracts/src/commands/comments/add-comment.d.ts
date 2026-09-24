/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type WorkspaceId = string;
export type IdempotencyKey = string;

/**
 * FR-CMT-001. Append one flat-thread comment to a Resource (read access required). Anchor defaults to ResourceAnchor.
 */
export interface AddComment {
	resourceId: UserId;
	threadId?: WorkspaceId;
	body: string;
	anchor?: {};
	idempotencyKey: IdempotencyKey;
}
