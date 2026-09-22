/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type AccountStatusValue =
	| "PendingVerification"
	| "Active"
	| "Disabled"
	| "DeletionPending"
	| "Deleted";
export type SessionId = string;
export type SessionStatusValue =
	| "Active"
	| "Replaced"
	| "LoggedOut"
	| "Expired"
	| "Revoked";

export interface LoginWithPasswordResponse {
	accountId: UserId;
	accountStatus: AccountStatusValue;
	session: SessionSummary;
	recoveryModeRequired: boolean;
}
export interface SessionSummary {
	sessionId: SessionId;
	createdAt: string;
	lastSeenAt: string;
	expiresAt: string;
	currentDevice: boolean;
	status: SessionStatusValue;
	lastStrongAuthAt?: string | null;
}
