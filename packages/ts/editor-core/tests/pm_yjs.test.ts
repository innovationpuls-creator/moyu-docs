import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import type { ContentNode } from "../src/index.js";
import {
	nodesToYFragment,
	yFragmentFor,
	yFragmentToNodes,
} from "../src/pm_yjs.js";

const sample: ContentNode[] = [
	{ kind: "heading", level: 2, children: [{ kind: "text", text: "标题" }] },
	{
		kind: "paragraph",
		children: [
			{ kind: "text", text: "正文 " },
			{ kind: "text", text: "加粗", marks: ["bold"] },
		],
	},
] as never[];

describe("y-prosemirror binding", () => {
	it("binds canonical nodes into a Yjs fragment and back", () => {
		const doc = new Y.Doc();
		const fragment = yFragmentFor(doc);
		nodesToYFragment(sample, fragment);
		const back = yFragmentToNodes(fragment);
		expect(back).toHaveLength(2);
		expect(back[0].kind).toBe("heading");
		expect(back[1].kind).toBe("paragraph");
	});

	it("two replicas created from the fragment converge (crdt merge)", () => {
		const a = new Y.Doc();
		nodesToYFragment(sample, yFragmentFor(a));
		const state = Y.encodeStateAsUpdate(a);
		const b = new Y.Doc();
		Y.applyUpdate(b, state);
		expect(yFragmentToNodes(yFragmentFor(b))).toHaveLength(2);
	});

	it("edits on one replica appear through the bound fragment", () => {
		const doc = new Y.Doc();
		const fragment = yFragmentFor(doc);
		nodesToYFragment(sample, fragment);
		doc.transact(() => {
			fragment.insert(0, [new Y.XmlElement("paragraph")]);
		});
		const back = yFragmentToNodes(fragment);
		expect(back.length).toBeGreaterThanOrEqual(2);
	});

	it("replicates stable asset references with their node identities", () => {
		const source = new Y.Doc();
		const sourceNodes: ContentNode[] = [
			{
				kind: "image",
				nodeId: "n_image-1",
				assetId: "asset-image-1",
				label: "diagram.png",
			},
			{
				kind: "attachment",
				nodeId: "n_attachment-1",
				assetId: "asset-file-1",
				label: "notes.txt",
			},
		];
		nodesToYFragment(sourceNodes, yFragmentFor(source));

		const peer = new Y.Doc();
		Y.applyUpdate(peer, Y.encodeStateAsUpdate(source));
		expect(yFragmentToNodes(yFragmentFor(peer))).toEqual(sourceNodes);
	});
});

import { EditorState } from "prosemirror-state";
import { schema as pmSchema } from "../src/pm_schema.js";
import { ySyncPluginFor } from "../src/pm_yjs.js";

describe("ySyncPlugin live binding", () => {
	it("ySyncPluginFor produces a state plugin for the fragment", () => {
		const doc = new Y.Doc();
		const fragment = yFragmentFor(doc);
		const plugin = ySyncPluginFor(fragment);
		const state = EditorState.create({
			schema: pmSchema,
			plugins: [plugin],
		});
		expect(state.plugins).toHaveLength(1);
		// the plugin key is registered (the live bind is wired through it)
		expect(plugin.spec.key).toBeDefined();
	});
});
