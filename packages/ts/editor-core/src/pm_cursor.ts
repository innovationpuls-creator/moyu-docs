/**
 * Remote-caret rendering (arch 05 §cursor): the presence op carries a cursor
 * selection offsets into the shared text; this module maps them to ProseMirror
 * positions and decorates the actual editing surface with a named caret and
 * selection range.
 */

import type { Node as PMNode } from "prosemirror-model";
import { Plugin, PluginKey } from "prosemirror-state";
import { Decoration, DecorationSet } from "prosemirror-view";
import { assetReferenceToken } from "./asset_reference.js";

export interface CursorPosition {
	text: string;
	anchor: number;
	head: number;
	participantId: string;
	displayName: string;
	color: string;
}

export type CursorProvider = () => CursorPosition | null;
export type CursorsProvider = () => CursorProvider[];

export const remoteCursorKey = new PluginKey<DecorationSet>("remoteCursor");

/** Resolve an offset in the OUTER plain text to a PM document position
 * (walking blocks; offset beyond the text clamps to the end). */
export function resolveCursorPosition(
	doc: PMNode,
	outerText: string,
	cursor: number,
): number {
	const clamped = Math.max(0, Math.min(cursor, outerText.length));
	let remaining = clamped;
	let position = 0;
	for (let index = 0; index < doc.childCount; index += 1) {
		const block = doc.child(index);
		const blockText =
			block.type.name === "image" || block.type.name === "attachment"
				? assetReferenceToken(
						block.type.name,
						String(block.attrs.assetId ?? ""),
						String(block.attrs.label ?? ""),
					)
				: block.textContent;
		const blockTextLength = blockText.length;
		if (block.type.name === "image" || block.type.name === "attachment") {
			if (remaining === 0) return position;
			if (remaining <= blockTextLength) return position + block.nodeSize;
			remaining -= blockTextLength;
		} else if (remaining <= blockTextLength) {
			return Math.min(position + 1 + remaining, position + block.nodeSize - 1);
		} else {
			remaining -= blockTextLength;
		}
		position += block.nodeSize;
		if (index < doc.childCount - 1 && remaining > 0) remaining -= 1;
	}
	return doc.content.size;
}

/** Decoration plugin: renders the remote caret widget at the resolved
 * position of the CURRENT doc text. */
export function remoteCursorPlugin(provider: CursorProvider): Plugin {
	return remoteCursorsPlugin(() => [provider]);
}

/** Multi-peer variant: renders ONE caret widget per provider. */
export function remoteCursorsPlugin(providers: CursorsProvider): Plugin {
	return new Plugin<DecorationSet>({
		key: remoteCursorKey,
		state: {
			init: () => DecorationSet.empty,
			apply: (tr, set) => {
				if (!tr.docChanged && !tr.getMeta(remoteCursorKey)) {
					return set.map(tr.mapping, tr.doc);
				}
				const all = providers()
					.map((provider) => provider())
					.filter((cursor): cursor is CursorPosition => cursor !== null);
				const decorations: Decoration[] = [];
				for (const [index, provided] of all.entries()) {
					const anchor = resolveCursorPosition(
						tr.doc,
						provided.text,
						provided.anchor,
					);
					const head = resolveCursorPosition(
						tr.doc,
						provided.text,
						provided.head,
					);
					const color = /^#[0-9a-f]{6}$/i.test(provided.color)
						? provided.color
						: "#637789";
					if (anchor !== head) {
						decorations.push(
							Decoration.inline(
								Math.min(anchor, head),
								Math.max(anchor, head),
								{
									class: "remote-selection-range",
									style: `background-color: ${color}26; box-shadow: inset 0 -2px ${color}`,
								},
							),
						);
					}
					const caret =
						typeof document === "undefined"
							? ({ nodeType: 1 } as unknown as HTMLElement)
							: document.createElement("span");
					if (typeof document !== "undefined") {
						caret.className = "remote-caret-marker";
						caret.dataset.testid = `remote-caret-${index}`;
						caret.style.setProperty("--remote-caret-color", color);
						const label = document.createElement("span");
						label.className = "remote-caret-label";
						label.textContent = provided.displayName;
						caret.append(label);
					}
					decorations.push(Decoration.widget(head, caret, { side: 1 }));
				}
				return DecorationSet.create(tr.doc, decorations);
			},
		},
		props: {
			decorations: (state) =>
				remoteCursorKey.getState(state) ?? DecorationSet.empty,
		},
	});
}
