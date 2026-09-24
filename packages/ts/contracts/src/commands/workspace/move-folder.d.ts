/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type FolderId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-006. Move Folder within the same Project only; reject cycles and cross-Project parents transactionally.
 */
export interface MoveFolder {
	folderId: FolderId;
	destinationParentFolderId: FolderId | null;
	idempotencyKey: IdempotencyKey;
}
