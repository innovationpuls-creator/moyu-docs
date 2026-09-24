/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;

/**
 * FR-WRL-003. List Workspace metadata records the authenticated Account is a member of (Owner or Member), newest first. Authority: Permission membership.
 */
export interface ListWorkspacesResponse {
	workspaces: {
		workspaceId: WorkspaceId;
		name: string;
		membershipKind: "Owner" | "Member";
		lifecycle: "Active" | "DeletionPending" | "Deleted";
		createdAt: string;
	}[];
}
