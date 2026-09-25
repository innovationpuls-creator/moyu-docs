/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type UserId = string;

export interface RemoveProjectMemberResponse {
	removed: true;
	projectId: ProjectId;
	accountId: UserId;
}
