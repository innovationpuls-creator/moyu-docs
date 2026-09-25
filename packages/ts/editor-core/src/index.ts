import { toggleMark } from "prosemirror-commands";
import type { Node as PMNode } from "prosemirror-model";
import { EditorState, TextSelection } from "prosemirror-state";
import { EditorView } from "prosemirror-view";
import {
	prosemirrorToYXmlFragment,
	ySyncPlugin,
	yXmlFragmentToProseMirrorRootNode,
} from "y-prosemirror";
import * as Y from "yjs";
import { schema } from "./pm_schema.js";

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

/** Public editor model. The Y.Doc stays private to Editor Core. */
export interface TextDocument {
	getText(): string;
	setText(value: string): void;
	onTextChange(listener: (value: string) => void): () => void;
	applyRemoteUpdate(update: Uint8Array): void;
	flushLocalUpdates(): Uint8Array[];
	exportState(): Uint8Array;
	stateVector(): Uint8Array;
	mountEditor(host: HTMLElement): TextEditorSurface;
	destroy(): void;
}

export interface TextEditorSurface {
	toggleMark(mark: "strong" | "em" | "code"): void;
	selectText(text: string): boolean;
	focus(): void;
	destroy(): void;
}

function documentFromText(value: string): PMNode {
	return schema.nodeFromJSON({
		type: "doc",
		content: value.split("\n").map((line) => ({
			type: "paragraph",
			content: line ? [{ type: "text", text: line }] : [],
		})),
	});
}

function replaceFragmentFromText(
	doc: Y.Doc,
	fragment: Y.XmlFragment,
	value: string,
): void {
	doc.transact(() => {
		if (fragment.length > 0) fragment.delete(0, fragment.length);
		prosemirrorToYXmlFragment(documentFromText(value), fragment);
	}, "editor-api");
}

/** Plain-text projection of the canonical Y.XmlFragment content. */
function textFromFragment(fragment: Y.XmlFragment): string {
	const root = yXmlFragmentToProseMirrorRootNode(fragment, schema);
	return root.textBetween(0, root.content.size, "\n");
}

/** Create a local-first Yjs-backed document without exposing its Y.Doc. */
export function createTextDocument(seed?: Uint8Array): TextDocument {
	const doc = new Y.Doc();
	if (seed && seed.byteLength > 0) Y.applyUpdate(doc, seed, "remote");
	const fragment = doc.getXmlFragment("prosemirror");
	// Migrate the previous runtime's Y.Text-only cache into Editor Core's
	// canonical ProseMirror/Y.XmlFragment representation.
	if (fragment.length === 0) {
		replaceFragmentFromText(doc, fragment, doc.getText("content").toString());
	}
	const updates: Uint8Array[] = [];
	const textListeners = new Set<(value: string) => void>();
	doc.on("update", (update: Uint8Array, origin: unknown) => {
		if (origin !== "remote") updates.push(update.slice());
		const value = textFromFragment(fragment);
		for (const listener of textListeners) listener(value);
	});
	return {
		getText: () => textFromFragment(fragment),
		setText(value) {
			if (textFromFragment(fragment) === value) return;
			replaceFragmentFromText(doc, fragment, value);
		},
		onTextChange(listener) {
			textListeners.add(listener);
			return () => textListeners.delete(listener);
		},
		applyRemoteUpdate(update) {
			Y.applyUpdate(doc, update, "remote");
		},
		flushLocalUpdates: () => updates.splice(0, updates.length),
		exportState: () => Y.encodeStateAsUpdate(doc),
		stateVector: () => Y.encodeStateVector(doc),
		mountEditor(host) {
			const state = EditorState.create({
				schema,
				plugins: [ySyncPlugin(fragment)],
			});
			const view = new EditorView(host, { state });
			return {
				toggleMark(mark) {
					const command = toggleMark(schema.marks[mark]);
					command(view.state, view.dispatch);
					view.focus();
				},
				selectText(value) {
					if (!value) return false;
					let from: number | null = null;
					view.state.doc.descendants((node, position) => {
						if (from !== null || !node.isText || !node.text) return;
						const offset = node.text.indexOf(value);
						if (offset >= 0) from = position + offset;
					});
					if (from === null) return false;
					view.dispatch(
						view.state.tr.setSelection(
							TextSelection.create(view.state.doc, from, from + value.length),
						),
					);
					view.focus();
					return true;
				},
				focus: () => view.focus(),
				destroy() {
					view.destroy();
				},
			};
		},
		destroy: () => doc.destroy(),
	};
}
