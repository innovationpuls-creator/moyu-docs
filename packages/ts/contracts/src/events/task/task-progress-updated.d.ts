/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type EventId = string;
export type TaskId = string;

/**
 * A task progress snapshot under the current authoritative attempt fence.
 */
export interface TaskProgressUpdated {
	eventId: EventId;
	eventType: "TaskProgressUpdated";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	payload: TaskProgressUpdatedPayload;
}
export interface TaskProgressUpdatedPayload {
	taskId: TaskId;
	taskType: string;
	state:
		| "Created"
		| "Queued"
		| "Running"
		| "WaitingForUser"
		| "Retrying"
		| "Succeeded"
		| "PartialSucceeded"
		| "Failed"
		| "Cancelled";
	stage: string | null;
	messageCode: string | null;
	current: number | null;
	total: number | null;
	percentage: number | null;
}
