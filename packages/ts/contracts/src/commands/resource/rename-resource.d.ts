/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-RC-004. Rename one authorized Resource; sibling names (normalized, incl. Trashed/Purged) stay reserved.
 */
export interface RenameResource {
	resourceId: UserId;
	name: string;
	idempotencyKey: IdempotencyKey;
}
