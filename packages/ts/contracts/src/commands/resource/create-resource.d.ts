/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type FolderId = string;
export type IdempotencyKey = string;

/**
 * FR-RC-001. Create a Resource inside an authorized Project (the Project's Workspace Owner). Sibling names (normalized, incl. Trashed/Purged) are reserved.
 */
export interface CreateResource {
	projectId: WorkspaceId;
	folderId?: FolderId | null;
	resourceType: "document" | "code" | "markdown" | "text";
	name: string;
	idempotencyKey: IdempotencyKey;
}
