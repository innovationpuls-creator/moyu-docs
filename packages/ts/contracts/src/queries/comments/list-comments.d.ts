/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type CommentId = string;
export type ThreadId = string;
export type UserId = string;

/**
 * FR-CMT-002. List flat-thread comments of a Resource, oldest first.
 */
export interface ListCommentsResponse {
	resourceId: ResourceId;
	items: {
		commentId: CommentId;
		threadId: ThreadId;
		authorAccountId: UserId;
		body: string;
		anchor: {};
		createdAt: string;
		status: "Open" | "Resolved" | "Detached";
		createdBy: UserId;
		resolvedAt: string | null;
		resolvedBy: UserId | null;
	}[];
}
