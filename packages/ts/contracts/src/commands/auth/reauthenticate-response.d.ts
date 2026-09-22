/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export interface ReauthenticateResponse {
	messageKey: string;
	reauthenticatedAt: string;
	validUntil: string;
	windowSeconds: number;
}
