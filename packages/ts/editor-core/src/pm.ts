/**
 * ProseMirror-shaped document adapter (arch 02 §editor): maps the canonical
 * content-node tree to ProseMirror node JSON and back. Unknown PM node types
 * are rejected, never silently dropped.
 */

import type { ContentNode, TextNode } from "./index.js";
import { ContentNodeError, validateNode } from "./index.js";

export type ProseMirrorJson = {
	type: string;
	attrs?: Record<string, unknown>;
	content?: ProseMirrorJson[];
	text?: string;
	marks?: Array<{ type: string }>;
};

const PM_MARK_NAMES: Record<string, string> = {
	bold: "strong",
	italic: "em",
	code: "code",
};

function textNodeToPm(node: TextNode): ProseMirrorJson {
	const marks = (node.marks ?? []).map((mark) => ({
		type: PM_MARK_NAMES[mark] ?? mark,
	}));
	return {
		type: "text",
		text: node.text,
		...(marks.length > 0 ? { marks } : {}),
	};
}

/** Canonical nodes -> ProseMirror node JSON (the editor layer serializes this
 * JSON into a y-prosemirror doc). */
export function toProseMirror(nodes: ContentNode[]): ProseMirrorJson {
	nodes.forEach((node) => {
		validateNode(node);
	});
	return {
		type: "doc",
		content: nodes.map((node) => {
			switch (node.kind) {
				case "text":
					return textNodeToPm(node);
				case "paragraph":
					return {
						type: "paragraph",
						content: (node.children ?? []).map(textNodeToPm),
					};
				case "heading":
					return {
						type: "heading",
						attrs: { level: node.level },
						content: (node.children ?? []).map(textNodeToPm),
					};
				case "list":
					return {
						type: node.ordered ? "orderedList" : "bulletList",
						content: (node.children ?? []).map((child) => ({
							type: "listItem",
							content: [
								{
									type: "paragraph",
									content: (child.children ?? []).map(textNodeToPm),
								},
							],
						})),
					};
				case "image":
					return {
						type: "image",
						attrs: {
							nodeId: node.nodeId,
							assetId: node.assetId,
							label: node.label,
						},
					};
				case "attachment":
					return {
						type: "attachment",
						attrs: {
							nodeId: node.nodeId,
							assetId: node.assetId,
							label: node.label,
						},
					};
				default:
					throw new ContentNodeError(
						`$: unsupported kind ${(node as { kind: string }).kind}`,
					);
			}
		}),
	};
}

/** ProseMirror node JSON -> canonical nodes; unknown PM types rejected. */
export function fromProseMirror(doc: ProseMirrorJson | unknown): ContentNode[] {
	if (typeof doc !== "object" || doc === null) {
		throw new ContentNodeError("$: expected a doc node");
	}
	const root = doc as { type?: string; content?: ProseMirrorJson[] };
	if (root.type !== "doc") {
		throw new ContentNodeError(`$: expected type "doc", got ${root.type}`);
	}
	return (root.content ?? []).map(pmNodeToCanonical);
}

function pmNodeToCanonical(item: ProseMirrorJson): ContentNode {
	switch (item.type) {
		case "text":
			return { kind: "text", text: item.text ?? "" };
		case "paragraph":
			return {
				kind: "paragraph",
				children: (item.content ?? []).map(pmTextOrThrow),
			};
		case "heading": {
			const level = Number(item.attrs?.level ?? 1) as 1 | 2 | 3;
			return {
				kind: "heading",
				level,
				children: (item.content ?? []).map(pmTextOrThrow),
			};
		}
		case "bulletList":
		case "orderedList":
			return {
				kind: "list",
				...(item.type === "orderedList" ? { ordered: true } : {}),
				children: (item.content ?? []).map((listItem) => {
					if (listItem.type !== "listItem") {
						throw new ContentNodeError(
							`list children must be listItems, got ${listItem.type}`,
						);
					}
					const paragraph = (listItem.content ?? [])[0];
					return pmNodeToCanonical(paragraph) as {
						kind: "paragraph";
					};
				}),
			};
		case "image":
		case "attachment": {
			const attrs = item.attrs ?? {};
			const node: ContentNode = {
				kind: item.type as "image" | "attachment",
				nodeId: String(attrs.nodeId ?? ""),
				assetId: String(attrs.assetId ?? ""),
				label: String(attrs.label ?? ""),
			};
			validateNode(node);
			return node;
		}
		default:
			throw new ContentNodeError(`unknown pm type ${item.type}`);
	}
}

function pmTextOrThrow(item: ProseMirrorJson): TextNode {
	if (item.type !== "text") {
		throw new ContentNodeError(`expected a text node, got ${item.type}`);
	}
	return { kind: "text", text: item.text ?? "" };
}
