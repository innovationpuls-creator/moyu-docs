/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type FolderId = string;

export interface TrashFolderResponse {
	folderId: FolderId;
	lifecycle: "Trashed";
	effectiveDescendantLifecycle: "Trashed";
	trashedAt: string;
	purgeEligibleAt: string;
}
