/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type EventId = string;
export type WorkspaceId = string;
export type ProjectId = string;
export type UserId = string;

/**
 * FR-WRL-008. Fact that Project ancestor lifecycle transitioned from Trashed to Active; descendants inherit restored state while retaining stable IDs.
 */
export interface ProjectRestored {
	eventId: EventId;
	eventType: "ProjectRestored";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: ProjectRestoredPayload;
}
export interface ProjectRestoredPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	actorAccountId: UserId;
}
