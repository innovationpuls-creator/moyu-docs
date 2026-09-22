/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-025/026/027. Single-use, 15-minute reset token in the request body, marked x-sensitive (doc 28 §57). Token is never echoed in the response. On success all old sessions are invalidated and no new session is auto-created (PRD FR-AUTH-027).
 */
export interface ResetPassword {
	token: string;
	newPassword: string;
}
