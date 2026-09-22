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
 * CancelAccountDeletion is a no-body Command (registry requestBody: none, doc 28 §8): the client sends no request body and OpenAPI declares no requestBody, so this file's root is the Response and no request schema exists. FR-AUTH-031: restore to the pre-deletion status (Active or PendingVerification), userId unchanged; reachable only while the account is DeletionPending, otherwise the AccountNotInDeletion error applies.
 */
export interface CancelAccountDeletionResponse {
	messageKey: string;
	accountStatus: AccountStatusValue;
	restoredAt: string;
}
