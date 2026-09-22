/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-006. Response carries account status, the current session summary, and whether the caller is forced into Account Recovery Mode (PRD FR-AUTH-032: DeletionPending -> recovery mode only). The session credential is delivered as a Secure/HttpOnly Set-Cookie (modeled in OpenAPI), not in this body.
 */
export interface LoginWithPassword {
	email: string;
	password: string;
}
