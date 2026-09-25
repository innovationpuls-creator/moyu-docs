/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type InvitationId = string;

export interface RevokeWorkspaceInvitationResponse {
	invitationId: InvitationId;
	state: "Expired" | "Revoked";
	expiresAt: string;
}
