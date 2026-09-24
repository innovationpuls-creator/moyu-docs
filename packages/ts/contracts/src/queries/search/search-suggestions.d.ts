/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;

/**
 * FR-SRC-003. Corpus prefix suggestions within a workspace.
 */
export interface SearchSuggestionsResponse {
	workspaceId: WorkspaceId;
	prefix: string;
	suggestions: string[];
}
