/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;

/**
 * Anonymous, read-only view resolved through an active share link. Share tokens and owner metadata are not exposed.
 */
export interface OpenPublicSharedResourceResponse {
	resourceId: ResourceId;
	name: string;
	resourceType: "document" | "code" | "markdown" | "text";
	snapshot: {} | null;
	journalSeq: number;
}
