/**
 * Content-node model (arch 02): the canonical document tree shared by the
 * editor, Yjs and serialization. Kinds are frozen; unknown kinds are rejected,
 * never silently accepted.
 */

export type ContentNodeKind = "text" | "paragraph" | "heading" | "list";

export interface TextNode {
	kind: "text";
	text: string;
	marks?: Array<"bold" | "italic" | "code">;
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

export type ContentNode = TextNode | ParagraphNode | HeadingNode | ListNode;

const KIND_SET: ReadonlySet<string> = new Set([
	"text",
	"paragraph",
	"heading",
	"list",
]);

export class ContentNodeError extends Error {}

export function validateNode(node: ContentNode, path = "$"): void {
	if (typeof node !== "object" || node === null) {
		throw new ContentNodeError(`${path}: node must be an object`);
	}
	if (!KIND_SET.has(node.kind)) {
		throw new ContentNodeError(`${path}: unknown kind ${String(node.kind)}`);
	}
	switch (node.kind) {
		case "text":
			if (typeof node.text !== "string") {
				throw new ContentNodeError(`${path}: text requires a string`);
			}
			break;
		case "heading":
			if (![1, 2, 3].includes(node.level)) {
				throw new ContentNodeError(`${path}: heading level must be 1|2|3`);
			}
			validateChildren(node.children, path);
			break;
		case "paragraph":
			validateChildren(node.children, path);
			break;
		case "list":
			if (node.children !== undefined) {
				node.children.forEach((child, i) => {
					if (child.kind !== "paragraph") {
						throw new ContentNodeError(
							`${path}.children[${i}]: list items must be paragraphs`,
						);
					}
					validateNode(child, `${path}.children[${i}]`);
				});
			}
			break;
	}
}

function validateChildren(
	children: TextNode[] | undefined,
	path: string,
): void {
	if (children === undefined) return;
	children.forEach((child, i) => {
		if (child.kind !== "text") {
			throw new ContentNodeError(
				`${path}.children[${i}]: expected a text node`,
			);
		}
		validateNode(child, `${path}.children[${i}]`);
	});
}

export function parseDoc(json: unknown): ContentNode[] {
	if (!Array.isArray(json)) {
		throw new ContentNodeError("$: document must be an array of nodes");
	}
	json.forEach((node, i) => {
		validateNode(node as ContentNode, `$[${i}]`);
	});
	return json as ContentNode[];
}

/** Plain-text projection (what the journal stores as the body text). */
export function toText(nodes: ContentNode[]): string {
	const parts: string[] = [];
	for (const node of nodes) {
		switch (node.kind) {
			case "text":
				parts.push(node.text);
				break;
			case "paragraph":
				parts.push((node.children ?? []).map((c) => c.text).join(""));
				break;
			case "heading":
				parts.push((node.children ?? []).map((c) => c.text).join(""));
				break;
			case "list":
				parts.push(
					(node.children ?? [])
						.map((p) => (p.children ?? []).map((c) => c.text).join(""))
						.join("\n"),
				);
				break;
		}
	}
	return parts.join("\n");
}
