/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type ProjectId = string;
export type ResourceId = string;
export type UserId = string;

export interface PermissionChanged {
	scopeType: "workspace" | "project" | "resource";
	scopeId: WorkspaceId | ProjectId | ResourceId;
	workspaceId: WorkspaceId;
	accountId?: UserId;
	action: string;
	role?: "Owner" | "Manage" | "Edit" | "Comment" | "Read" | "Member" | null;
	occurredAt: string;
}
