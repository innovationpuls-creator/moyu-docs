/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;
export type FolderId = string;

/**
 * FR-RC-006. List Resources of an authorized Project (workspace-member authority). Trashed/Purged rows carry their lifecycle; navigation surfaces Active only.
 */
export interface ListResourcesResponse {
	projectId: WorkspaceId;
	items: {
		resourceId: UserId;
		folderId?: FolderId | null;
		name: string;
		resourceType: "document" | "code" | "markdown" | "text";
		lifecycle: "Active" | "Trashed" | "Purging" | "Purged";
	}[];
}
