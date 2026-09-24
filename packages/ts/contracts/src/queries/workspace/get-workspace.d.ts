/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;

/**
 * FR-WRL-001/002. Read one authorized Workspace metadata record by stable identity.
 */
export interface GetWorkspaceResponse {
	workspaceId: WorkspaceId;
	name: string;
	ownerAccountId: UserId;
	lifecycle: "Active" | "DeletionPending" | "Deleted";
	createdAt: string;
	updatedAt: string;
}
