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
 * FR-WRL-006. Fact that Folder parent changed within one Project; the parent must remain in that Project and the tree remains acyclic.
 */
export interface FolderMoved {
	eventId: EventId;
	eventType: "FolderMoved";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: FolderMovedPayload;
}
export interface FolderMovedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	folderId: FolderId;
	previousParentFolderId: FolderId | null;
	parentFolderId: FolderId | null;
	actorAccountId: UserId;
}
