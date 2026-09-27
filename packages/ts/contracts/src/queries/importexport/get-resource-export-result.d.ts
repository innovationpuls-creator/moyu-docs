/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;

/**
 * FR-IE-001. Export one Resource as a versioned Moyu Docs exchange document (metadata + latest snapshot).
 */
export interface GetResourceExportResultResponse {
	kind: "dom.resource.export.v1";
	schemaVersion: "1.0.0";
	exportedAt: string;
	resource: {
		resourceId: ResourceId;
		resourceType: "document" | "code" | "markdown" | "text";
		name: string;
	};
	content: {
		snapshot: {} | null;
		journalSeq: number;
	};
}
