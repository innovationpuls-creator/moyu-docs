/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type ResourceId = string;
export type IdempotencyKey = string;

/**
 * Internal Realtime command. Replace semantic Resource content by applying a valid Yjs update to the current Y.Doc, durably append it, and broadcast it.
 */
export interface ReplaceResourceContent {
	resourceId: ResourceId;
	operationId: IdempotencyKey;
	expectedJournalSeq?: number;
	createdBy: string | null;
	reason: "import" | "history-restore" | "ai-changeset";
	restoreTargetSeq?: number;
	snapshot: ContentSnapshot;
}
export interface ContentSnapshot {
	text: string;
	nodes: (TextNode | ParagraphNode | HeadingNode | ListNode | AssetNode)[];
}
export interface TextNode {
	kind: "text";
	text: string;
	marks?: ("bold" | "italic" | "code")[];
}
export interface ParagraphNode {
	kind: "paragraph";
	children?: TextNode[];
}
export interface HeadingNode {
	kind: "heading";
	level: 1 | 2 | 3;
	children?: TextNode[];
}
export interface ListNode {
	kind: "list";
	ordered?: boolean;
	children?: ParagraphNode[];
}
export interface AssetNode {
	kind: "image" | "attachment";
	nodeId: string;
	assetId: string;
	label: string;
}
