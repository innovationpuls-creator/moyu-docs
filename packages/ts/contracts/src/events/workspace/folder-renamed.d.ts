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
 * FR-WRL-005. Fact that Folder display name changed without changing its stable identity.
 */
export interface FolderRenamed {
	eventId: EventId;
	eventType: "FolderRenamed";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: FolderRenamedPayload;
}
export interface FolderRenamedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	folderId: FolderId;
	previousName: string;
	name: string;
	actorAccountId: UserId;
}
