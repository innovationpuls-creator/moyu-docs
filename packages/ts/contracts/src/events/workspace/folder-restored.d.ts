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
 * FR-WRL-008. Fact that Folder ancestor lifecycle transitioned to Active; descendants inherit restored state with stable identities.
 */
export interface FolderRestored {
	eventId: EventId;
	eventType: "FolderRestored";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: FolderRestoredPayload;
}
export interface FolderRestoredPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	folderId: FolderId;
	parentFolderId: FolderId | null;
	name: string;
	actorAccountId: UserId;
}
