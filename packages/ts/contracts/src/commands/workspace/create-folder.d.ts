/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type FolderId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-005. Create Folder metadata. Parent, when present, must be in the same Project.
 */
export interface CreateFolder {
	projectId: ProjectId;
	parentFolderId: FolderId | null;
	name: string;
	idempotencyKey: IdempotencyKey;
}
