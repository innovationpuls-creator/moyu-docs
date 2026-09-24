/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type FolderId = string;

/**
 * FR-WRL-004/005. List immediate Folder metadata children only; no Resource content is returned.
 */
export interface ListFolderChildrenResponse {
	projectId: ProjectId;
	parentFolderId: FolderId | null;
	items: FolderSummary[];
	nextCursor: string | null;
}
export interface FolderSummary {
	folderId: FolderId;
	name: string;
	lifecycle: "Active" | "Trashed" | "Deleted";
	hasChildren: boolean;
}
