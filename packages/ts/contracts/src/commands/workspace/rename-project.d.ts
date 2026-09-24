/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-003. Rename Project metadata; sibling collision comparison is canonical and display value is preserved.
 */
export interface RenameProject {
	projectId: ProjectId;
	name: string;
	idempotencyKey: IdempotencyKey;
}
