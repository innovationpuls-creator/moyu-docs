/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type AccountStatusValue =
	| "PendingVerification"
	| "Active"
	| "Disabled"
	| "DeletionPending"
	| "Deleted";

/**
 * FR-AUTH-022. Only the actor's own account facts. Per doc 16 §66 the Auth module must NOT answer Permission questions, so no capability enumeration is included (capability answers belong to doc 07); canCreateWorkspace is a status-derived product boolean, not a Permission capability set. This Query has no request body (registry requestBody: none, doc 28 §8): the client sends no request body, so this file's root is the Response and no request schema exists.
 */
export interface GetCurrentAccountResponse {
	accountId: UserId;
	primaryEmail: string;
	accountStatus: AccountStatusValue;
	emailVerifiedAt: string | null;
	createdAt: string;
	canCreateWorkspace: boolean;
	inAccountRecoveryMode: boolean;
}
