/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;

/**
 * Upload one immutable binary Asset for a Resource. The HTTP body is multipart/form-data; the file is never written into the Resource Y.Doc. Requests require Idempotency-Key; the same key and same actor, Resource, bytes, MIME type, and original name replay the original Asset, while a different request returns IDEMPOTENCY_KEY_CONFLICT.
 */
export interface UploadAsset {
	resourceId: ResourceId;
	/**
	 * The file bytes sent as the multipart field named file.
	 */
	file: string;
	mime?: string | null;
}
