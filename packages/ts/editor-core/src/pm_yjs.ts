/**
 * y-prosemirror binding (arch 02/05, ADR-0050): maps the editor-core PM
 * schema root node <-> a Yjs XmlFragment so rich edits can ride the SAME
 * Yjs doc as the journal text. The textarea stays the journal source of
 * truth; this module grounds the binding the rich surface will use.
 */

import type { Node as PMNode } from "prosemirror-model";
import type { Plugin } from "prosemirror-state";
import {
	prosemirrorToYXmlFragment,
	ySyncPlugin,
	yXmlFragmentToProseMirrorRootNode,
} from "y-prosemirror";
import type * as Y from "yjs";
import type { ContentNode } from "./index.js";
import { fromProseMirror } from "./pm.js";
import { docFromNodes, schema } from "./pm_schema.js";

export type { PMNode };

/** The fragment living in the Yjs doc ("prosemirror" root map key). */
export function yFragmentFor(resourceDoc: Y.Doc): Y.XmlFragment {
	return resourceDoc.getXmlFragment("prosemirror");
}

/** Canonical content nodes -> a Yjs fragment (bind). */
export function nodesToYFragment(
	nodes: ContentNode[],
	target: Y.XmlFragment,
): void {
	const root = docFromNodes(nodes);
	prosemirrorToYXmlFragment(root, target);
}

/** Yjs fragment -> canonical content nodes (bind). */
export function yFragmentToNodes(fragment: Y.XmlFragment): ContentNode[] {
	const root = yXmlFragmentToProseMirrorRootNode(fragment, schema);
	const json = root.toJSON();
	return fromProseMirror(json as never);
}

/** Live y-prosemirror binding (ADR-0050): the EditorState plugin that keeps
 * the PM document synchronized with the Yjs fragment BOTH ways. */
export function ySyncPluginFor(fragment: Y.XmlFragment): Plugin {
	// the plugin derives the schema from the EditorState it attaches to
	return ySyncPlugin(fragment);
}
