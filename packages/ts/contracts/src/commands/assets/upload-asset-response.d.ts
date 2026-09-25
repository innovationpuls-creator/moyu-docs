/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type AssetId = string;

export interface UploadAssetResponse {
	assetId: AssetId;
	sha256: string;
	sizeBytes: number;
}
