/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;
export type ProjectId = string;
export type FolderId = string;

/**
 * FR-SRC-001. Workspace-scoped Resource name/body search (member authority).
 */
export interface SearchWorkspaceResponse {
	workspaceId: WorkspaceId;
	query: string;
	items: {
		resourceId: UserId;
		projectId?: ProjectId;
		folderId?: FolderId | null;
		name: string;
		resourceType: "document" | "code" | "markdown" | "text";
		score: number;
		snippet?: string | null;
	}[];
}
