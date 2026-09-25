/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type InvitationId = string;

export interface RevokeWorkspaceInvitation {
	workspaceId: WorkspaceId;
	invitationId: InvitationId;
}
