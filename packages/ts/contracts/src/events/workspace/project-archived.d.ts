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
 * FR-WRL-007. Fact that Project metadata transitioned to Archived; Resource/session effects are owned elsewhere.
 */
export interface ProjectArchived {
	eventId: EventId;
	eventType: "ProjectArchived";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: ProjectArchivedPayload;
}
export interface ProjectArchivedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	actorAccountId: UserId;
}
