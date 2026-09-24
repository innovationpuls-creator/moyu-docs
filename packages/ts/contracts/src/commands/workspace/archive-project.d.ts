/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-007. Archive is reversible and makes a Project read-only; it is not Trash.
 */
export interface ArchiveProject {
	projectId: ProjectId;
	idempotencyKey: IdempotencyKey;
}
