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
 * FR-AUTH-030 AC-030.2 / FR-AUTH-032 AC-032.2. The deletion / recovery-mode view: deletionRequestedAt, gracePeriodDaysRemaining and executeAfter (scheduled final deletion) are null unless the account is DeletionPending. This Query has no request body (registry requestBody: none, doc 28 §8): the client sends no request body, so this file's root is the Response and no request schema exists.
 */
export interface GetAccountStatusResponse {
	accountStatus: AccountStatusValue;
	inAccountRecoveryMode: boolean;
	deletionRequestedAt: string | null;
	gracePeriodDaysRemaining: number | null;
	executeAfter: string | null;
	canCancelDeletion: boolean;
}
