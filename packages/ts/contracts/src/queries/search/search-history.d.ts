/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-SRC-002. The account's recent search queries, newest first, de-duplicated.
 */
export interface SearchHistoryResponse {
	items: {
		query: string;
		lastUsedAt: string | null;
	}[];
}
