/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type EventId = string;
export type WorkspaceId = string;
export type ProjectId = string;
export type FolderId = string;
export type UserId = string;

/**
 * FR-WRL-008. Fact that Folder ancestor lifecycle transitioned to Trashed; descendants inherit without per-descendant writes. Does not claim Resource session closure or physical cleanup.
 */
export interface FolderTrashed {
	eventId: EventId;
	eventType: "FolderTrashed";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: FolderTrashedPayload;
}
export interface FolderTrashedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	folderId: FolderId;
	actorAccountId: UserId;
	purgeEligibleAt: string;
}
