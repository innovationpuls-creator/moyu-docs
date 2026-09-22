/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-002. Single-use, 24h verification token in the request body, marked x-sensitive (doc 28 §57). Token is never echoed in the response (doc 28 §58).
 */
export interface VerifyEmail {
	token: string;
}
