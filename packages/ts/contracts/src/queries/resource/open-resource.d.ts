/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type WorkspaceId = string;

/**
 * FR-RC-001/006. Read one authorized Resource's metadata and latest materialized snapshot (checkpoint). Authority: resource ownership (Permission). 404 when the Resource is trashed/purged or not authorized.
 */
export interface OpenResourceResponse {
	resourceId: UserId;
	projectId: WorkspaceId;
	resourceType: "document" | "code" | "markdown" | "text";
	name: string;
	lifecycle: "Active" | "Trashed" | "Purging" | "Purged";
	journalSeq: number;
	snapshot: {} | null;
}
