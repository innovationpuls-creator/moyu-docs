/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ProjectId = string;
export type WorkspaceId = string;

export interface CreateProjectResponse {
	projectId: ProjectId;
	workspaceId: WorkspaceId;
	name: string;
	createdAt: string;
}
