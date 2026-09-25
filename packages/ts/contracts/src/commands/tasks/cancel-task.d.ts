/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type TaskId = string;

/**
 * Requests cooperative cancellation and returns the accepted task state.
 */
export interface CancelTaskResponse {
	task: TaskSummary;
}
/**
 * Current authoritative task summary. Progress values are null when unavailable; this shape does not imply that a task type currently emits progress.
 */
export interface TaskSummary {
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
	updatedAt: string | null;
	retryCount: number;
	retryOfTaskId: TaskId | null;
	cancelRequestedAt: string | null;
	queuedAt: string | null;
	startedAt: string | null;
	finishedAt: string | null;
	failureCode: string | null;
}
