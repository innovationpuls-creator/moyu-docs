/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;

export interface GetResourceCapabilitiesResponse {
	resourceId: ResourceId;
	canRead: boolean;
	canUpdate: boolean;
	canComment: boolean;
	canManage: boolean;
	canResolveCommentThread: boolean;
	canReopenCommentThread: boolean;
}
