/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type WorkspaceId = string;

export interface AddCommentResponse {
	commentId: UserId;
	threadId: WorkspaceId;
	body: string;
	createdAt: string;
}
