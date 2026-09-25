/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ChangeSetId = string;

/**
 * Apply a previously proposed ChangeSet after explicit user approval.
 */
export interface ApplyChangeSetResponse {
	changesetId: ChangeSetId;
	journalSeq: number;
	status: "Applied";
}
