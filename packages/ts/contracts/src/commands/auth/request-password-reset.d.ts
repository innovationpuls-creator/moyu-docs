/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-024. Anti-enumeration: identical external response whether or not the email is registered (PRD FR-AUTH-007). Rate-limited (AC-024.3). The request carries only the email; the reset link is delivered out-of-band.
 */
export interface RequestPasswordReset {
	email: string;
}
