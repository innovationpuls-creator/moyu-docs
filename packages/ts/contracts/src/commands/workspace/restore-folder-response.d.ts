/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type FolderId = string;
export type ProjectId = string;

export interface RestoreFolderResponse {
	folderId: FolderId;
	projectId: ProjectId;
	parentFolderId: FolderId | null;
	name: string;
	lifecycle: "Active";
	restoredDescendantCount: number;
	restoredAt: string;
}
