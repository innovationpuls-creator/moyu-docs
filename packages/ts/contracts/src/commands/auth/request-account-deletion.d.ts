/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type AccountStatusValue =
	| "PendingVerification"
	| "Active"
	| "Disabled"
	| "DeletionPending"
	| "Deleted";

/**
 * RequestAccountDeletion is a no-body Command (registry requestBody: none, doc 28 §8): the client sends no request body and OpenAPI declares no requestBody, so this file's root is the Response and no request schema exists. The recent-authentication requirement (10-minute window, FR-AUTH-034) is satisfied by the session's lastStrongAuthAt, never by a request field. FR-AUTH-029/030; the response exposes the 30-day grace window (executeAfter = scheduled final deletion).
 */
export interface RequestAccountDeletionResponse {
	messageKey: string;
	accountStatus: AccountStatusValue;
	deletionRequestedAt: string;
	gracePeriodDaysRemaining: number;
	executeAfter: string;
}
