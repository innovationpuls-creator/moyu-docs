/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ThreadId = string;
export type ResourceId = string;

/**
 * FR-CMT-006. Result of reopening a resolved comment thread.
 */
export interface ReopenCommentThreadResponse {
	threadId: ThreadId;
	resourceId: ResourceId;
	status: "Open";
	resolvedAt: null;
	resolvedBy: null;
}
