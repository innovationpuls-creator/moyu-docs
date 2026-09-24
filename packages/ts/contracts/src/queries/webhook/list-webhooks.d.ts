/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;

/**
 * FR-WEB-002. Workspace webhook subscriptions, newest first (no body).
 */
export interface ListWebhooksResponse {
	workspaceId: WorkspaceId;
	items: {
		subscriptionId: UserId;
		url: string;
		status: string;
		createdAt: string | null;
	}[];
}
