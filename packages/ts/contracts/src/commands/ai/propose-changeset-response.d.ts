/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ChangeSetId = string;
export type ResourceId = string;

export interface ProposeChangeSetResponse {
	changesetId: ChangeSetId;
	resourceId: ResourceId;
	instruction: string;
	operations: {
		[k: string]: unknown;
	}[];
	status: "Proposed";
}
