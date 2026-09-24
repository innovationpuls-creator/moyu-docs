/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type ProjectId = string;

/**
 * FR-WRL-003/004. List authorized Project metadata in a Workspace; Resource content is never included.
 */
export interface ListProjectsResponse {
	workspaceId: WorkspaceId;
	items: ProjectSummary[];
	nextCursor: string | null;
}
export interface ProjectSummary {
	projectId: ProjectId;
	workspaceId: WorkspaceId;
	name: string;
	lifecycle: "Active" | "Archived" | "Trashed" | "Purging" | "Purged";
	updatedAt: string;
}
