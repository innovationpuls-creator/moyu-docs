/**
 * Yjs-prosemirror baseline binding (arch 02 §editor, arch 05): maps the PM
 * doc <-> the Yjs "content" text projection used by the journal. The rich
 * per-node XML-fragment binding (y-prosemirror) is a future editor upgrade;
 * this baseline is the loss-tolerant, type-guarded contract the current
 * textarea editor serializes through.
 */

import { ContentNodeError, toText } from "./index.js";
import type { ProseMirrorJson } from "./pm.js";
import { fromProseMirror, toProseMirror } from "./pm.js";

/** PM doc -> the plain-text projection stored in Y.Text("content"). */
export function pmToYjsText(pm: ProseMirrorJson): string {
	return toText(fromProseMirror(pm));
}

/** Yjs "content" text -> a single-paragraph PM doc (loss-tolerant baseline;
 * block structure is re-derivable from the richer node snapshot). */
export function yjsTextToPm(text: string): ProseMirrorJson {
	if (typeof text !== "string") {
		throw new ContentNodeError("yjs text must be a string");
	}
	return toProseMirror([
		{ kind: "paragraph", children: [{ kind: "text", text }] },
	]);
}
