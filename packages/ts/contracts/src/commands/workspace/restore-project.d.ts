/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-008. Restore Project ancestor lifecycle and all descendant metadata state atomically; preserve stable IDs, use current Permission, and never purge content.
 */
export interface RestoreProject {
	projectId: ProjectId;
	idempotencyKey: IdempotencyKey;
}
