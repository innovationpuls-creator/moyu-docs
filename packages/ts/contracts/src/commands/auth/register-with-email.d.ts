/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-001. Request root = email + password. Password length 12-128 per PRD FR-AUTH-001 / OQ-3 (reject common/leaked passwords at the application layer). Response is the anti-enumeration uniform payload (PRD FR-AUTH-005/007, BDD 'two requests get identical external hint'); the auto-established session (BDD FR-AUTH-001, PRD AC-001.1) is delivered as a Secure/HttpOnly Set-Cookie, modeled in OpenAPI, NOT in this body.
 */
export interface RegisterWithEmail {
	email: string;
	password: string;
}
