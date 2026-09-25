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
import {
	assetReferenceToken,
	parseAssetReferenceToken,
} from "./asset_reference.js";
import {
	type CursorPosition,
	remoteCursorKey,
	remoteCursorsPlugin,
} from "./pm_cursor.js";
import { docFromNodes, schema } from "./pm_schema.js";

/**
 * Content-node model (arch 02): the canonical document tree shared by the
 * editor, Yjs and serialization. Kinds are frozen; unknown kinds are rejected,
 * never silently accepted.
 */

export type ContentNodeKind =
	| "text"
	| "paragraph"
	| "heading"
	| "list"
	| "image"
	| "attachment";

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

export interface ImageNode {
	kind: "image";
	nodeId: string;
	assetId: string;
	label: string;
}

export interface AttachmentNode {
	kind: "attachment";
	nodeId: string;
	assetId: string;
	label: string;
}

export type ContentNode =
	| TextNode
	| ParagraphNode
	| HeadingNode
	| ListNode
	| ImageNode
	| AttachmentNode;

export type AssetNodeKind = "image" | "attachment";

export interface AssetReference {
	kind: AssetNodeKind;
	nodeId: string;
	assetId: string;
	label: string;
}

export interface NewAssetReference extends Omit<AssetReference, "nodeId"> {}

const KIND_SET: ReadonlySet<string> = new Set([
	"text",
	"paragraph",
	"heading",
	"list",
	"image",
	"attachment",
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
		case "image":
		case "attachment":
			if (typeof node.nodeId !== "string" || node.nodeId.length === 0) {
				throw new ContentNodeError(`${path}: asset node requires a nodeId`);
			}
			if (typeof node.assetId !== "string" || node.assetId.length === 0) {
				throw new ContentNodeError(`${path}: asset node requires an assetId`);
			}
			if (typeof node.label !== "string") {
				throw new ContentNodeError(`${path}: asset node requires a label`);
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
			case "image":
				parts.push(assetReferenceToken(node.kind, node.assetId, node.label));
				break;
			case "attachment":
				parts.push(assetReferenceToken(node.kind, node.assetId, node.label));
				break;
		}
	}
	return parts.join("\n");
}

/** Public editor model. The Y.Doc stays private to Editor Core. */
export interface TextDocument {
	getText(): string;
	setText(value: string): void;
	setNodes(nodes: ContentNode[]): void;
	onTextChange(listener: (value: string) => void): () => void;
	applyRemoteUpdate(update: Uint8Array): void;
	applyRemoteUpdates(updates: readonly Uint8Array[]): void;
	flushLocalUpdates(): Uint8Array[];
	exportState(): Uint8Array;
	stateVector(): Uint8Array;
	mountEditor(
		host: HTMLElement,
		options?: TextEditorOptions,
	): TextEditorSurface;
	destroy(): void;
}

export interface TextEditorOptions {
	readOnly?: boolean;
	renderAsset?: (
		container: HTMLElement,
		reference: AssetReference,
	) => (() => void) | undefined;
}

export interface TextEditorSurface {
	toggleMark(mark: "strong" | "em" | "code"): void;
	selectText(text: string): boolean;
	getSelectionOffsets(): { anchor: number; head: number };
	onSelectionChange(
		listener: (selection: { anchor: number; head: number }) => void,
	): () => void;
	setRemoteCursors(cursors: CursorPosition[]): void;
	insertAssets(references: readonly NewAssetReference[]): void;
	focus(): void;
	destroy(): void;
}

function assetTokenForNode(node: PMNode): string | null {
	if (node.type.name !== "image" && node.type.name !== "attachment")
		return null;
	return assetReferenceToken(
		node.type.name,
		String(node.attrs.assetId ?? ""),
		String(node.attrs.label ?? ""),
	);
}

function preservedAssetNodeIds(fragment: Y.XmlFragment): Map<string, string[]> {
	const ids = new Map<string, string[]>();
	if (fragment.length === 0) return ids;
	const root = yXmlFragmentToProseMirrorRootNode(fragment, schema);
	root.descendants((node) => {
		if (node.type.name !== "image" && node.type.name !== "attachment") return;
		const key = `${node.type.name}:${String(node.attrs.assetId)}`;
		const existing = ids.get(key) ?? [];
		existing.push(String(node.attrs.nodeId));
		ids.set(key, existing);
	});
	return ids;
}

function newNodeId(): string {
	return `n_${crypto.randomUUID()}`;
}

function documentFromText(
	value: string,
	assetNodeIds: Map<string, string[]> = new Map(),
): PMNode {
	const content = value.split("\n").map((line) => {
		const reference = parseAssetReferenceToken(line);
		if (reference) {
			const nodeId =
				assetNodeIds.get(`${reference.kind}:${reference.assetId}`)?.shift() ??
				newNodeId();
			return {
				type: reference.kind,
				attrs: {
					nodeId,
					assetId: reference.assetId,
					label: reference.label,
				},
			};
		}
		return {
			type: "paragraph",
			content: line ? [{ type: "text", text: line }] : [],
		};
	});
	return schema.nodeFromJSON({ type: "doc", content });
}

function replaceFragmentFromText(
	doc: Y.Doc,
	fragment: Y.XmlFragment,
	value: string,
): void {
	const nextDocument = documentFromText(value, preservedAssetNodeIds(fragment));
	replaceFragmentFromDocument(doc, fragment, nextDocument);
}

function replaceFragmentFromDocument(
	doc: Y.Doc,
	fragment: Y.XmlFragment,
	nextDocument: PMNode,
): void {
	doc.transact(() => {
		if (fragment.length > 0) fragment.delete(0, fragment.length);
		prosemirrorToYXmlFragment(nextDocument, fragment);
	}, "editor-api");
}

/** Plain-text projection of the canonical Y.XmlFragment content. */
function textFromFragment(fragment: Y.XmlFragment): string {
	const root = yXmlFragmentToProseMirrorRootNode(fragment, schema);
	return root.textBetween(
		0,
		root.content.size,
		"\n",
		(node) => assetTokenForNode(node) ?? "",
	);
}

function createAssetNodeView(
	node: PMNode,
	renderAsset?: TextEditorOptions["renderAsset"],
) {
	const kind = node.type.name as AssetNodeKind;
	const reference: AssetReference = {
		kind,
		nodeId: String(node.attrs.nodeId),
		assetId: String(node.attrs.assetId),
		label: String(node.attrs.label ?? ""),
	};
	const dom = document.createElement(kind === "image" ? "img" : "div");
	if (kind === "image") {
		dom.className = "editor-asset-image";
		(dom as HTMLImageElement).alt = reference.label || "图片";
		(dom as HTMLImageElement).draggable = true;
	}
	dom.dataset.assetId = reference.assetId;
	dom.dataset.nodeId = reference.nodeId;
	dom.dataset.assetKind = kind;
	dom.dataset.testid = `inline-asset-${reference.assetId}`;
	const dispose = renderAsset?.(dom, reference);
	if (!renderAsset && kind === "attachment")
		dom.textContent = reference.label || "附件";
	return {
		dom,
		update: () => false,
		selectNode: () => dom.classList.add("ProseMirror-selectednode"),
		deselectNode: () => dom.classList.remove("ProseMirror-selectednode"),
		destroy: () => dispose?.(),
	};
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
		setNodes(nodes) {
			const nextDocument =
				nodes.length > 0
					? docFromNodes(nodes)
					: schema.nodeFromJSON({
							type: "doc",
							content: [{ type: "paragraph" }],
						});
			replaceFragmentFromDocument(doc, fragment, nextDocument);
		},
		onTextChange(listener) {
			textListeners.add(listener);
			return () => textListeners.delete(listener);
		},
		applyRemoteUpdate(update) {
			Y.applyUpdate(doc, update, "remote");
		},
		applyRemoteUpdates(batch) {
			if (batch.length === 0) return;
			Y.applyUpdate(doc, Y.mergeUpdates([...batch]), "remote");
		},
		flushLocalUpdates: () => updates.splice(0, updates.length),
		exportState: () => Y.encodeStateAsUpdate(doc),
		stateVector: () => Y.encodeStateVector(doc),
		mountEditor(host, options) {
			let remoteCursors: CursorPosition[] = [];
			const selectionListeners = new Set<
				(selection: { anchor: number; head: number }) => void
			>();
			let state = EditorState.create({
				schema,
				plugins: [
					ySyncPlugin(fragment),
					remoteCursorsPlugin(() =>
						remoteCursors.map((cursor) => () => cursor),
					),
				],
			});
			const viewRef: { current?: EditorView } = {};
			const view = new EditorView(host, {
				state,
				editable: () => options?.readOnly !== true,
				nodeViews: {
					image: (node) => createAssetNodeView(node, options?.renderAsset),
					attachment: (node) => createAssetNodeView(node, options?.renderAsset),
				},
				dispatchTransaction(transaction) {
					state = state.apply(transaction);
					const activeView = viewRef.current;
					if (activeView !== undefined) {
						activeView.updateState(state);
					}
					if (
						activeView !== undefined &&
						(transaction.selectionSet || transaction.docChanged)
					) {
						const selection = readSelectionOffsets(activeView);
						for (const listener of selectionListeners) listener(selection);
					}
				},
			});
			viewRef.current = view;
			if (view.state !== state) view.updateState(state);
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
				getSelectionOffsets: () => readSelectionOffsets(view),
				onSelectionChange(listener) {
					selectionListeners.add(listener);
					listener(readSelectionOffsets(view));
					return () => selectionListeners.delete(listener);
				},
				setRemoteCursors(cursors) {
					remoteCursors = cursors;
					view.dispatch(view.state.tr.setMeta(remoteCursorKey, true));
				},
				insertAssets(references) {
					if (references.length === 0) return;
					if (view.isDestroyed) {
						throw new Error("Cannot insert an asset into a destroyed editor.");
					}
					view.focus();
					const { $from } = view.state.selection;
					const insertionPosition =
						$from.depth > 0 ? $from.after(1) : $from.pos;
					const assetNodes = references.map((reference) => {
						const nodeType = schema.nodes[reference.kind];
						if (!nodeType)
							throw new Error(`Unsupported asset node: ${reference.kind}`);
						return nodeType.create({ ...reference, nodeId: newNodeId() });
					});
					view.dispatch(view.state.tr.insert(insertionPosition, assetNodes));
					const insertedNodeIds = new Set(
						assetNodes.map((node) => String(node.attrs.nodeId)),
					);
					const liveNodeIds = new Set<string>();
					view.state.doc.descendants((node) => {
						if (
							(node.type.name === "image" || node.type.name === "attachment") &&
							insertedNodeIds.has(String(node.attrs.nodeId))
						) {
							liveNodeIds.add(String(node.attrs.nodeId));
						}
					});
					if (liveNodeIds.size !== insertedNodeIds.size) {
						throw new Error("The editor did not accept the asset insertion.");
					}
					const projectedText = textFromFragment(fragment);
					if (
						references.some(
							(reference) =>
								!projectedText.includes(
									assetReferenceToken(
										reference.kind,
										reference.assetId,
										reference.label,
									),
								),
						)
					) {
						throw new Error(
							"The inserted asset is missing from the document text.",
						);
					}
				},
				focus: () => view.focus(),
				destroy() {
					selectionListeners.clear();
					view.destroy();
				},
			};
		},
		destroy: () => doc.destroy(),
	};
}

function readSelectionOffsets(view: EditorView): {
	anchor: number;
	head: number;
} {
	const { anchor, head } = view.state.selection;
	const textOffset = (position: number) =>
		view.state.doc.textBetween(
			0,
			position,
			"\n",
			(node) => assetTokenForNode(node) ?? "",
		).length;
	return {
		anchor: textOffset(anchor),
		head: textOffset(head),
	};
}
