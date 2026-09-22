/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type LogoutStatusValue = "LoggedOut" | "AlreadyLoggedOut";

/**
 * Logout is a no-body Command (registry requestBody: none, doc 28 §8): the client sends no request body and OpenAPI declares no requestBody, so this file's root is the Response and no request schema exists. FR-AUTH-020; idempotent, so sessionStatus = AlreadyLoggedOut when the session was already invalid (BDD 'logout is idempotent').
 */
export interface LogoutResponse {
	messageKey: string;
	sessionStatus: LogoutStatusValue;
}
