/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type UserId = string;

export interface SetProjectMemberRole {
	projectId: ProjectId;
	accountId: UserId;
	role: "Owner" | "Manage" | "Edit" | "Comment" | "Read";
}
