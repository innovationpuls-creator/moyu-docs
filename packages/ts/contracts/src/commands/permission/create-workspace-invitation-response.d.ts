/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type InvitationId = string;
export type WorkspaceId = string;
export type UserId = string;

export interface CreateWorkspaceInvitationResponse {
	invitationId: InvitationId;
	workspaceId: WorkspaceId;
	targetEmail: string;
	role: "Member";
	state: "Pending";
	expiresAt: string;
	createdBy: UserId;
	createdAt: string;
	invitationUrl: string;
	notificationSent?: boolean;
}
