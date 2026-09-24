/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;

export interface TrashProjectResponse {
	projectId: ProjectId;
	lifecycle: "Trashed";
	effectiveDescendantLifecycle: "Trashed";
	trashedAt: string;
	purgeEligibleAt: string;
}
