/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;

export interface ArchiveProjectResponse {
	projectId: ProjectId;
	lifecycle: "Archived";
	updatedAt: string;
}
