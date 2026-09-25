import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { createTextDocument } from "../src/index.js";
import { yFragmentFor, yFragmentToNodes } from "../src/pm_yjs.js";

describe("Editor Core text document", () => {
	it("stores plain text in the ProseMirror Yjs fragment and reopens it", () => {
		const document = createTextDocument();
		document.setText("第一段\n第二段");

		const reopened = createTextDocument(document.exportState());
		expect(reopened.getText()).toBe("第一段\n第二段");
		document.destroy();
		reopened.destroy();
	});

	it("sets canonical nodes and shares rich checkpoint content through Yjs", () => {
		const author = createTextDocument();
		const replica = createTextDocument(author.exportState());
		const checkpoint = [
			{
				kind: "heading" as const,
				level: 2 as const,
				children: [{ kind: "text" as const, text: "Review" }],
			},
			{
				kind: "image" as const,
				nodeId: "node-image-1",
				assetId: "asset-image-1",
				label: "diagram.png",
			},
			{
				kind: "attachment" as const,
				nodeId: "node-file-1",
				assetId: "asset-file-1",
				label: "notes.txt",
			},
		];

		author.setNodes(checkpoint);
		replica.applyRemoteUpdates(author.flushLocalUpdates());
		const reopened = createTextDocument(replica.exportState());
		const reopenedDoc = new Y.Doc();
		Y.applyUpdate(reopenedDoc, reopened.exportState());

		expect(yFragmentToNodes(yFragmentFor(reopenedDoc))).toEqual(checkpoint);
		expect(reopened.getText()).toBe(
			"Review\n![diagram.png](asset://asset-image-1)\n[notes.txt](asset://asset-file-1)",
		);

		author.destroy();
		replica.destroy();
		reopened.destroy();
		reopenedDoc.destroy();
	});

	it("migrates an existing Y.Text-only offline update", () => {
		const legacyDocument = new Y.Doc();
		legacyDocument.getText("content").insert(0, "待恢复的旧草稿");
		const document = createTextDocument(Y.encodeStateAsUpdate(legacyDocument));

		expect(document.getText()).toBe("待恢复的旧草稿");
		const reopened = createTextDocument(document.exportState());
		expect(reopened.getText()).toBe("待恢复的旧草稿");

		legacyDocument.destroy();
		document.destroy();
		reopened.destroy();
	});

	it("notifies subscribers after local and remote document updates", () => {
		const author = createTextDocument();
		const replica = createTextDocument(author.exportState());
		const changes: string[] = [];
		const unsubscribe = replica.onTextChange((text) => changes.push(text));

		author.setText("远端更新");
		replica.applyRemoteUpdate(author.flushLocalUpdates()[0]);

		expect(changes).toContain("远端更新");
		unsubscribe();
		author.destroy();
		replica.destroy();
	});

	it("round-trips inline asset references without changing their node identity", () => {
		const document = createTextDocument();
		document.setText(
			"前文\n![diagram %28final%29 1.png](asset://asset-image-1)\n[notes.txt](asset://asset-file-1)\n后文",
		);
		const originalText = document.getText();
		const originalState = document.exportState();
		const originalYDoc = new Y.Doc();
		Y.applyUpdate(originalYDoc, originalState);
		const originalNodes = yFragmentToNodes(yFragmentFor(originalYDoc));
		const originalAssetNodes = originalNodes.filter(
			(node) => node.kind === "image" || node.kind === "attachment",
		);

		const reopened = createTextDocument(originalState);
		reopened.setText(originalText.replace("前文", "新的前文"));
		const reopenedYDoc = new Y.Doc();
		Y.applyUpdate(reopenedYDoc, reopened.exportState());
		const reopenedAssetNodes = yFragmentToNodes(
			yFragmentFor(reopenedYDoc),
		).filter((node) => node.kind === "image" || node.kind === "attachment");

		expect(originalText).toContain(
			"![diagram %28final%29 1.png](asset://asset-image-1)",
		);
		expect(originalAssetNodes.map((node) => node.nodeId)).toEqual(
			reopenedAssetNodes.map((node) => node.nodeId),
		);
		expect(reopened.getText()).toBe(
			"新的前文\n![diagram %28final%29 1.png](asset://asset-image-1)\n[notes.txt](asset://asset-file-1)\n后文",
		);
		document.destroy();
		reopened.destroy();
		originalYDoc.destroy();
		reopenedYDoc.destroy();
	});
});
