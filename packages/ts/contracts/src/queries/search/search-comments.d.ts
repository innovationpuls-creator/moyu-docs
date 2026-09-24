/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;

/**
 * FR-SRC-004. Search undeleted comment bodies within a workspace.
 */
export interface SearchCommentsResponse {
	workspaceId: WorkspaceId;
	query: string;
	items: {
		commentId: UserId;
		threadId: UserId;
		resourceId: UserId;
		resourceName: string;
		body: string;
	}[];
}
