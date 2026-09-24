/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-IE-002. Import one exchange document INTO an existing Resource: the imported snapshot becomes a new checkpoint and the import is recorded as a journal op.
 */
export interface ImportResource {
	resourceId: UserId;
	document: {};
	idempotencyKey: IdempotencyKey;
}
