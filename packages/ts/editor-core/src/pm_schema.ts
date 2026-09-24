/**
 * ProseMirror runtime grounding (ADR-0050): the editor-core Schema validates
 * PM docs structurally and round-trips them against the canonical node model.
 * The textarea stays the journal source of truth; PM is the rich view layer.
 */

import { type Node as PMNode, Schema } from "prosemirror-model";

import type { ContentNode, TextNode } from "./index.js";
import { fromProseMirror, toProseMirror } from "./pm.js";

export const schema = new Schema({
	nodes: {
		doc: { content: "block+" },
		paragraph: { content: "inline*", group: "block" },
		heading: {
			content: "inline*",
			group: "block",
			attrs: { level: { default: 1 } },
		},
		bulletList: { content: "listItem+", group: "block" },
		listItem: { content: "paragraph block*" },
		text: { group: "inline" },
	},
	marks: {
		strong: {},
		em: {},
		code: {},
	},
});

/** Build a validated ORIGIN node from canonical content nodes. */
export function docFromNodes(nodes: ContentNode[]): PMNode {
	const json = toProseMirror(nodes);
	const viaSchema = schema.nodeFromJSON(json);
	if (viaSchema === null) {
		throw new Error("pm doc does not fit the editor-core schema");
	}
	viaSchema.check();
	return viaSchema;
}

/** Canonical nodes from an ORIGIN PM node (JSON round-trip). */
export function nodesFromDoc(docNode: PMNode): ContentNode[] {
	const json = docNode.toJSON();
	const nodes = fromProseMirror(json as never);
	nodes.forEach((node) => {
		if (node.kind === "text" && typeof (node as TextNode).text !== "string") {
			throw new Error("text node without text");
		}
	});
	return nodes;
}

/** Plain text of the PM doc (including list/newline structure). */
export function textContent(node: PMNode): string {
	return node.textContent;
}
