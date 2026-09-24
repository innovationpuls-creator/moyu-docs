/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type WorkspaceId = string;
export type UserId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-011 Permission-owned command contract. Transfer Workspace Owner only to an existing Workspace member. Permission atomically retains the former Owner as a normal member, removes inherited Workspace-wide Project management, preserves independent Project Owner rows, and maintains one authoritative Workspace Owner. This schema specifies the boundary only; no Permission storage adapter is implemented by Lifecycle.
 */
export interface TransferWorkspaceOwner {
	workspaceId: WorkspaceId;
	newOwnerAccountId: UserId;
	idempotencyKey: IdempotencyKey;
}
