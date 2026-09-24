/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-008. Trash a Project by changing authoritative ancestor lifecycle state; all descendants inherit Trashed without per-descendant writes. No Purge or physical cleanup is performed.
 */
export interface TrashProject {
	projectId: ProjectId;
	idempotencyKey: IdempotencyKey;
}
