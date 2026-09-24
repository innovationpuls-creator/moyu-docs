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
 * FR-WRL-008. Fact that Project ancestor lifecycle transitioned to Trashed; descendants inherit this state without per-descendant writes. Does not signal Resource session closure or physical cleanup.
 */
export interface ProjectTrashed {
	eventId: EventId;
	eventType: "ProjectTrashed";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: ProjectTrashedPayload;
}
export interface ProjectTrashedPayload {
	workspaceId: WorkspaceId;
	projectId: ProjectId;
	actorAccountId: UserId;
	purgeEligibleAt: string;
}
