/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ShareId = string;
export type ResourceId = string;
export type UserId = string;

export interface CreateResourceShareLinkResponse {
	shareLink: ShareLinkMetadata;
	shareUrl: string;
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
