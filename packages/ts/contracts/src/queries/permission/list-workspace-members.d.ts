/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;

export interface ListWorkspaceMembersResponse {
	members: {
		accountId: UserId;
		email: string;
		membershipKind: "Owner" | "Member";
		createdAt: string;
	}[];
}
