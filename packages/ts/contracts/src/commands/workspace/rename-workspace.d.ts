/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-002. Preserve display input; collision key is NFC + trim of edge whitespace + case-insensitive comparison. Workspace names are not globally unique.
 */
export interface RenameWorkspace {
	workspaceId: WorkspaceId;
	name: string;
	idempotencyKey: IdempotencyKey;
}
