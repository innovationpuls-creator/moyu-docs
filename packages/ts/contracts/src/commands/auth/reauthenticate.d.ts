/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-AUTH-034 / doc 16 §104-§105. Re-verify the password before high-risk operations (10-minute recent-auth window). Request = password (x-sensitive). Response expresses the window: reauthenticatedAt and validUntil (= reauthenticatedAt + 10m).
 */
export interface Reauthenticate {
	password: string;
}
