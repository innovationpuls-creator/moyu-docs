/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type IdempotencyKey = string;

/**
 * FR-WRL-001/011. Create a Workspace. Permission-owned bootstrap must atomically establish the requesting Account as its initial sole Workspace Owner; Lifecycle never writes membership rows.
 */
export interface CreateWorkspace {
	name: string;
	idempotencyKey: IdempotencyKey;
}
