/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-003. Create Project metadata under a Workspace. Permission supplies inherited authorization; independent Project Owner membership remains Permission-owned.
 */
export interface CreateProject {
	workspaceId: WorkspaceId;
	name: string;
	idempotencyKey: IdempotencyKey;
}
