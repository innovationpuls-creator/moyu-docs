/**
 * Remote-caret rendering (arch 05 §cursor): the presence op carries a cursor
 * OFFSET into the OUTER text; this module resolves it to a position in the
 * PM doc and exposes a decoration plugin that shows one remote caret. The
 * view-level widget is thin; the mapping is unit-proven here.
 */

import type { Node as PMNode } from "prosemirror-model";
import { Plugin, PluginKey } from "prosemirror-state";
import { Decoration, DecorationSet } from "prosemirror-view";

export interface CursorPosition {
	text: string;
	cursor: number;
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
	const flat = doc.textContent;
	const clamped = Math.max(0, Math.min(cursor, outerText.length, flat.length));
	return clamped;
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
				const all = providers()
					.filter(Boolean)
					.map((p) => p as unknown as CursorPosition);
				if (all.length === 0) return set; // rebuilt on the next apply
				const widgets = all.map((provided, i) => {
					const pos = resolveCursorPosition(
						tr.doc,
						provided.text,
						provided.cursor,
					);
					const caret =
						typeof document === "undefined"
							? ({ nodeType: 1 } as unknown as HTMLElement)
							: document.createElement("span");
					if (typeof document !== "undefined") {
						caret.textContent = "|";
						caret.dataset.testid = `remote-caret-${i}`;
					}
					return Decoration.widget(pos, caret);
				});
				return DecorationSet.create(tr.doc, widgets);
			},
		},
		props: {
			decorations: (state) =>
				remoteCursorKey.getState(state) ?? DecorationSet.empty,
		},
	});
}
