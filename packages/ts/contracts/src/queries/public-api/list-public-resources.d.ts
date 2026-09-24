/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;

/**
 * PUB-002. Machine-client readable resource list (integration-key auth).
 */
export interface GetPublicResourcesResponse {
	items: {
		resourceId: UserId;
		resourceType: string;
		name: string;
		updatedAt: string | null;
	}[];
}
