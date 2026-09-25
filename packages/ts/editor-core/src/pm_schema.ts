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
		doc: { content: "block+", toDOM: () => ["div", 0] },
		paragraph: {
			content: "inline*",
			group: "block",
			parseDOM: [{ tag: "p" }],
			toDOM: () => ["p", 0],
		},
		heading: {
			content: "inline*",
			group: "block",
			attrs: { level: { default: 1 } },
			parseDOM: [
				{ tag: "h1", attrs: { level: 1 } },
				{ tag: "h2", attrs: { level: 2 } },
				{ tag: "h3", attrs: { level: 3 } },
			],
			toDOM: (node) => [`h${node.attrs.level}`, 0],
		},
		bulletList: {
			content: "listItem+",
			group: "block",
			parseDOM: [{ tag: "ul" }],
			toDOM: () => ["ul", 0],
		},
		listItem: {
			content: "paragraph block*",
			parseDOM: [{ tag: "li" }],
			toDOM: () => ["li", 0],
		},
		image: {
			group: "block",
			atom: true,
			selectable: true,
			draggable: true,
			attrs: { nodeId: {}, assetId: {}, label: { default: "" } },
			parseDOM: [
				{
					tag: "img[data-asset-kind='image']",
					getAttrs: (dom) => {
						const element = dom as HTMLElement;
						return {
							nodeId: element.dataset.nodeId,
							assetId: element.dataset.assetId,
							label: element.dataset.label ?? element.getAttribute("alt") ?? "",
						};
					},
				},
				{
					tag: "figure[data-asset-kind='image']",
					getAttrs: (dom) => {
						const element = dom as HTMLElement;
						return {
							nodeId: element.dataset.nodeId,
							assetId: element.dataset.assetId,
							label: element.dataset.label ?? "",
						};
					},
				},
			],
			toDOM: (node) => [
				"img",
				{
					"data-asset-kind": "image",
					"data-node-id": node.attrs.nodeId,
					"data-asset-id": node.attrs.assetId,
					"data-label": node.attrs.label,
					alt: node.attrs.label,
				},
			],
		},
		attachment: {
			group: "block",
			atom: true,
			selectable: true,
			draggable: true,
			attrs: { nodeId: {}, assetId: {}, label: { default: "" } },
			parseDOM: [
				{
					tag: "div[data-asset-kind='attachment']",
					getAttrs: (dom) => {
						const element = dom as HTMLElement;
						return {
							nodeId: element.dataset.nodeId,
							assetId: element.dataset.assetId,
							label: element.dataset.label ?? "",
						};
					},
				},
			],
			toDOM: (node) => [
				"div",
				{
					"data-asset-kind": "attachment",
					"data-node-id": node.attrs.nodeId,
					"data-asset-id": node.attrs.assetId,
					"data-label": node.attrs.label,
				},
			],
		},
		text: { group: "inline" },
	},
	marks: {
		strong: {
			parseDOM: [{ tag: "strong" }, { tag: "b" }],
			toDOM: () => ["strong", 0],
		},
		em: {
			parseDOM: [{ tag: "em" }, { tag: "i" }],
			toDOM: () => ["em", 0],
		},
		code: {
			code: true,
			parseDOM: [{ tag: "code" }],
			toDOM: () => ["code", 0],
		},
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
