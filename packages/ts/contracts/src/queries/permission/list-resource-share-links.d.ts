/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type ShareId = string;
export type UserId = string;

export interface ListResourceShareLinksResponse {
	resourceId: ResourceId;
	shareLinks: ShareLinkMetadata[];
}
export interface ShareLinkMetadata {
	shareId: ShareId;
	resourceId: ResourceId;
	capability: "Read";
	status: "Active" | "Revoked" | "Expired";
	expiresAt: string | null;
	createdBy: UserId;
	createdAt: string;
	revokedAt: string | null;
}
