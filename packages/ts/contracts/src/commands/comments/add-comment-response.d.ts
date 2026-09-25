/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type CommentId = string;
export type ThreadId = string;

export interface AddCommentResponse {
	commentId: CommentId;
	threadId: ThreadId;
	body: string;
	createdAt: string;
}
