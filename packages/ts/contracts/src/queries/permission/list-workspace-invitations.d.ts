/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type InvitationId = string;
export type WorkspaceId = string;
export type UserId = string;

export interface ListWorkspaceInvitationsResponse {
	invitations: {
		invitationId: InvitationId;
		workspaceId: WorkspaceId;
		targetEmail: string;
		targetAccountId?: UserId | null;
		role: "Member";
		state: "Pending" | "Accepted" | "Expired" | "Revoked";
		expiresAt: string;
		createdBy: UserId;
		createdAt: string;
		acceptedAt?: string | null;
	}[];
}
