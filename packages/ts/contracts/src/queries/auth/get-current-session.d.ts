/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type SessionId = string;
export type SessionStatusValue =
	| "Active"
	| "Replaced"
	| "LoggedOut"
	| "Expired"
	| "Revoked";

/**
 * FR-AUTH-022. Must identify 'this is the current device' (BDD FR-AUTH-022: creation time + current device marker). currentDevice is always true for this endpoint since it returns the caller's own active session. This Query has no request body (registry requestBody: none, doc 28 §8): the client sends no request body, so this file's root is the Response and no request schema exists.
 */
export interface GetCurrentSessionResponse {
	sessionId: SessionId;
	createdAt: string;
	lastSeenAt: string;
	expiresAt: string;
	currentDevice: boolean;
	status: SessionStatusValue;
	lastStrongAuthAt?: string | null;
}
