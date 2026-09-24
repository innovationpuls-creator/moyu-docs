/**
 * Markdown projection (arch 02 §export): canonical content nodes <-> a
 * bounded Markdown subset (# headings, - lists, bold/italic/code marks).
 * Round-tripping is loss-tolerant for unsupported constructs (they degrade
 * to plain text) but never throws on input.
 */

import type { ContentNode, TextNode } from "./index.js";
import { ContentNodeError } from "./index.js";

const MARKDOWN_SYNTAX: Record<string, [string, string]> = {
	bold: ["**", "**"],
	italic: ["*", "*"],
	code: ["`", "`"],
};

function textToMd(
	text: string,
	marks?: Array<"bold" | "italic" | "code">,
): string {
	let out = text.replace(/\*/g, "\\*").replace(/`/g, "\\`");
	for (const mark of marks ?? []) {
		const [open, close] = MARKDOWN_SYNTAX[mark] ?? ["", ""];
		out = `${open}${out}${close}`;
	}
	return out;
}

/** Canonical nodes -> markdown (block level). */
export function nodesToMarkdown(nodes: ContentNode[]): string {
	const parts: string[] = [];
	for (const node of nodes) {
		switch (node.kind) {
			case "text":
				parts.push(textToMd(node.text, node.marks));
				break;
			case "paragraph":
				parts.push(
					(node.children ?? []).map((c) => textToMd(c.text, c.marks)).join(""),
				);
				break;
			case "heading":
				parts.push(
					"#".repeat(node.level) +
						" " +
						(node.children ?? [])
							.map((c) => textToMd(c.text, c.marks))
							.join(""),
				);
				break;
			case "list":
				for (const item of node.children ?? []) {
					parts.push(
						"- " +
							(item.children ?? [])
								.map((c) => textToMd(c.text, c.marks))
								.join(""),
					);
				}
				break;
		}
	}
	return parts.join("\n");
}

const BLOCK_PATTERN = /^(#{1,3})\s+(.*)$|^-\s+(.*)$|^(.*)$/;

function inlineFromMd(text: string): TextNode {
	// bounded inline parse: **bold**, *italic*, `code`
	const strong = /^\*\*(.+)\*\*$/.exec(text);
	if (strong) return { kind: "text", text: strong[1], marks: ["bold"] };
	const em = /^\*(.+)\*$/.exec(text);
	if (em) return { kind: "text", text: em[1], marks: ["italic"] };
	const code = /^`(.+)`$/.exec(text);
	if (code) return { kind: "text", text: code[1], marks: ["code"] };
	return { kind: "text", text };
}

/** Bounded markdown -> canonical nodes (unsupported syntax becomes text). */
export function markdownToNodes(markdown: string): ContentNode[] {
	const nodes: ContentNode[] = [];
	for (const rawLine of markdown.split("\n")) {
		if (rawLine.trim() === "") continue;
		const heading = /^(#{1,3})\s+(.*)$/.exec(rawLine);
		if (heading) {
			nodes.push({
				kind: "heading",
				level: heading[1].length as 1 | 2 | 3,
				children: [inlineFromMd(heading[2])],
			});
			continue;
		}
		const item = /^-\s+(.*)$/.exec(rawLine);
		if (item) {
			nodes.push({
				kind: "paragraph",
				children: [inlineFromMd(item[1])],
			});
			continue;
		}
		nodes.push({
			kind: "paragraph",
			children: [inlineFromMd(rawLine)],
		});
	}
	return nodes;
}

export function _mdErrorCheck(text: string): void {
	if (typeof text !== "string") {
		throw new ContentNodeError("markdown must be a string");
	}
}
