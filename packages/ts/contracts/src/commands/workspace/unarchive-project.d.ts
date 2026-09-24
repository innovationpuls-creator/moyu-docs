/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-007. Restore an Archived Project to Active; current Permission determines subsequent capabilities.
 */
export interface UnarchiveProject {
	projectId: ProjectId;
	idempotencyKey: IdempotencyKey;
}
