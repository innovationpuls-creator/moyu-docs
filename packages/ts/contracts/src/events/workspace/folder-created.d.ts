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
 * FR-WRL-005. Fact that Folder metadata was created in a Project tree.
 */
export interface FolderCreated {
	eventId: EventId;
	eventType: "FolderCreated";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: FolderCreatedPayload;
}
export interface FolderCreatedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	folderId: FolderId;
	parentFolderId: FolderId | null;
	name: string;
	actorAccountId: UserId;
}
