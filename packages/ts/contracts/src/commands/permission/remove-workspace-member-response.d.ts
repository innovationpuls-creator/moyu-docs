/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;

export interface RemoveWorkspaceMemberResponse {
	removed: true;
	workspaceId: WorkspaceId;
	accountId: UserId;
}
