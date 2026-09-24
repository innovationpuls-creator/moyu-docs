/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-INT-006. Current-window Public API usage per route for the session account.
 */
export interface GetApiUsageResponse {
	items: {
		route: string;
		requests: number;
		limit: number;
	}[];
}
