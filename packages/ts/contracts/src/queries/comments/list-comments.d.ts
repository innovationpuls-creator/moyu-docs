/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type WorkspaceId = string;

/**
 * FR-CMT-002. List flat-thread comments of a Resource, oldest first.
 */
export interface ListCommentsResponse {
	resourceId: UserId;
	items: {
		commentId: UserId;
		threadId: WorkspaceId;
		authorAccountId: UserId;
		body: string;
		anchor: {};
		createdAt: string;
	}[];
}
