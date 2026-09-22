/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-004. Rate-limited (60s cooldown, max 5 per 24h). The response exposes nextAllowedAt so the client can show the 60s countdown (BDD AC-004.3) without leaking account existence: the same payload is returned whether or not the email is registered.
 */
export interface ResendEmailVerification {
	email: string;
}
