/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type UserId = string;

export interface ListResourcePermissionsResponse {
	permissions: {
		resourceId: ResourceId;
		accountId: UserId;
		email: string;
		role: "Owner" | "Manage" | "Edit" | "Comment" | "Read";
		createdAt: string;
		updatedAt: string;
	}[];
}
