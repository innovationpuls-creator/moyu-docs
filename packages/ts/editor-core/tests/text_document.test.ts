import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { createTextDocument } from "../src/index.js";

describe("Editor Core text document", () => {
	it("stores plain text in the ProseMirror Yjs fragment and reopens it", () => {
		const document = createTextDocument();
		document.setText("第一段\n第二段");

		const reopened = createTextDocument(document.exportState());
		expect(reopened.getText()).toBe("第一段\n第二段");
		document.destroy();
		reopened.destroy();
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
});
