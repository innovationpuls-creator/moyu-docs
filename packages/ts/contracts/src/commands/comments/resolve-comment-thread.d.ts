/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ThreadId = string;
export type ResourceId = string;
export type UserId = string;

/**
 * FR-CMT-005. Result of resolving an open comment thread.
 */
export interface ResolveCommentThreadResponse {
	threadId: ThreadId;
	resourceId: ResourceId;
	status: "Resolved";
	resolvedAt: string;
	resolvedBy: UserId;
}
