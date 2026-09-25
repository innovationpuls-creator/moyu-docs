/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type WorkspaceId = string;
export type FolderId = string;

export interface CreateResourceResponse {
	resourceId: UserId;
	projectId: WorkspaceId;
	folderId?: FolderId | null;
	resourceType: "document" | "code" | "markdown" | "text";
	name: string;
	lifecycle: "Active" | "Trashed" | "Purging" | "Purged";
	createdAt: string;
}
