/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-RC-005. Restore one authorized Trashed Resource to Active (the sibling name stays reserved until physical purge).
 */
export interface RestoreResource {
	resourceId: UserId;
	idempotencyKey: IdempotencyKey;
}
