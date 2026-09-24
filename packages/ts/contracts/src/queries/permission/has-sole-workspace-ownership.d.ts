/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;

/**
 * FR-WRL-009/011 Permission-owned owner query adapter behind Auth WorkspaceOwnershipQueryPort. Evaluates the same authoritative membership source as Workspace create/transfer. The API actor is the authenticated account; no account ID is accepted from the request body.
 */
export interface HasSoleWorkspaceOwnershipResponse {
	hasSoleWorkspaceOwnership: boolean;
	workspaceId: WorkspaceId | null;
}
