/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type UserId = string;

export interface RemoveResourcePermission {
	resourceId: ResourceId;
	accountId: UserId;
}
