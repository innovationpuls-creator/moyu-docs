/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type UserId = string;

export interface ListProjectMembersResponse {
	members: {
		projectId: ProjectId;
		accountId: UserId;
		email: string;
		role: "Owner" | "Manage" | "Edit" | "Comment" | "Read";
		membershipKind: "Owner" | "Member";
		createdAt: string;
		updatedAt: string;
	}[];
}
