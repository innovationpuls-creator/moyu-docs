/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type AssetId = string;

/**
 * Metadata for binary assets attached to a Resource. Storage keys and object provider details are never returned.
 */
export interface ListResourceAssetsResponse {
	resourceId: ResourceId;
	assets: {
		assetId: AssetId;
		originalName: string;
		mime: string | null;
		sizeBytes: number;
		sha256: string;
		createdAt: string;
	}[];
}
