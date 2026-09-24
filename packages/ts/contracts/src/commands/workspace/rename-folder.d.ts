/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type FolderId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-005. Rename Folder metadata while preserving its stable Folder identity.
 */
export interface RenameFolder {
	folderId: FolderId;
	name: string;
	idempotencyKey: IdempotencyKey;
}
