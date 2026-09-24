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
 * FR-WRL-007. Fact that Project metadata transitioned from Archived to Active.
 */
export interface ProjectUnarchived {
	eventId: EventId;
	eventType: "ProjectUnarchived";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: ProjectUnarchivedPayload;
}
export interface ProjectUnarchivedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	actorAccountId: UserId;
}
