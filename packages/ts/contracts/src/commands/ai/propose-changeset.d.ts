/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;

/**
 * Create a reviewable AI proposal for one resource. Proposing never applies the change.
 */
export interface ProposeChangeSet {
	resourceId: ResourceId;
	instruction: string;
}
