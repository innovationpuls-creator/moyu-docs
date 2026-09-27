/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type IdempotencyKey = string;

/**
 * FR-IE-002. Import one exchange document INTO an existing Resource: the imported snapshot becomes a new checkpoint and the import is recorded as a journal op.
 */
export interface ImportResource {
	resourceId: ResourceId;
	document: ExportResourceResponse;
	idempotencyKey: IdempotencyKey;
}
/**
 * FR-IE-001. Export one Resource as a versioned Moyu Docs exchange document (metadata + latest snapshot).
 */
export interface ExportResourceResponse {
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
