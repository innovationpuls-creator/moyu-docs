/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type EventId = string;
export type RequestId = string;
export type WorkspaceId = string;
export type UserId = string;

/**
 * FR-WRL-001. Fact that Workspace metadata was created; initial Owner membership is established through the Permission-owned atomic bootstrap boundary.
 */
export interface WorkspaceCreated {
	eventId: EventId;
	eventType: "WorkspaceCreated";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	traceId?: RequestId;
	payload: WorkspaceCreatedPayload;
}
export interface WorkspaceCreatedPayload {
	workspaceId: WorkspaceId;
	actorAccountId: UserId;
	name: string;
}
