/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;

/**
 * FR-HS-001. Version timeline, oldest-first.
 */
export interface ListVersionsResponse {
	resourceId: UserId;
	items: {
		seq: number;
		kind: "Checkpoint" | "NamedVersion" | "Restore";
		label: string | null;
		author: string | null;
		occurredAt: string | null;
	}[];
}
