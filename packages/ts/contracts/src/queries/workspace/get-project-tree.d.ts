/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type ProjectId = string;
export type ProjectLifecycle =
	| "Active"
	| "Archived"
	| "Trashed"
	| "Purging"
	| "Purged";
export type FolderId = string;
export type FolderLifecycle = "Active" | "Trashed" | "Deleted";

/**
 * FR-WRL-004. Metadata-only, lazy-load-capable Project Tree; this Query never loads Resource content.
 */
export interface GetProjectTreeResponse {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	project: ProjectSummary;
	folders: FolderSummary[];
	nextCursor: string | null;
}
export interface ProjectSummary {
	name: string;
	lifecycle: ProjectLifecycle;
}
export interface FolderSummary {
	folderId: FolderId;
	parentFolderId: FolderId | null;
	name: string;
	lifecycle: FolderLifecycle;
	hasChildren: boolean;
}
