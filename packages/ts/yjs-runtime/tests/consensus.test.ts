/**
 * CRDT consensus property (arch 05): independent replicas that exchange only
 * their local updates converge to identical state, regardless of arrival order.
 */

import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { createDocument, setText } from "../src/index.js";

describe("yjs consensus", () => {
	it("two replicas converge after exchanging updates", () => {
		const a = createDocument();
		const b = createDocument();
		const at = a.doc.getText("content");
		const bt = b.doc.getText("content");
		at.insert(0, "hello ");
		bt.insert(0, "world");
		const aUpdates = a.flushUpdates();
		const bUpdates = b.flushUpdates();
		b.applyRemoteUpdate(aUpdates[0]);
		a.applyRemoteUpdate(bUpdates[0]);
		expect(a.text()).toBe(b.text());
		expect(a.text().length).toBeGreaterThan(0);
	});

	it("state export/import is lossless across replicas", () => {
		const a = createDocument();
		a.doc.getText("content").insert(0, "merged-state");
		const state = a.exportState();
		const c = createDocument(state);
		expect(c.text()).toBe("merged-state");
	});

	it("three-way merge converges", () => {
		const docs = [createDocument(), createDocument(), createDocument()];
		docs[0].doc.getText("content").insert(0, "A");
		docs[1].doc.getText("content").insert(0, "B");
		docs[2].doc.getText("content").insert(0, "C");
		const batch = docs.map((d) => d.flushUpdates().flat());
		// each replica applies the other two's updates in different orders
		docs[0].applyRemoteUpdate(batch[1][0]);
		docs[0].applyRemoteUpdate(batch[2][0]);
		docs[1].applyRemoteUpdate(batch[0][0]);
		docs[1].applyRemoteUpdate(batch[2][0]);
		docs[2].applyRemoteUpdate(batch[1][0]);
		docs[2].applyRemoteUpdate(batch[0][0]);
		const contents = docs.map((d) => d.text());
		expect(contents[0]).toBe(contents[1]);
		expect(contents[1]).toBe(contents[2]);
	});
});

describe("setText", () => {
	it("replaces the whole text and stays convergent", () => {
		const a = createDocument();
		const b = createDocument();
		setText(a, "first draft");
		const aUpdate = a.flushUpdates()[0];
		b.applyRemoteUpdate(aUpdate);
		setText(b, "second draft merged");
		const bUpdate = b.flushUpdates()[0];
		a.applyRemoteUpdate(bUpdate);
		// a converges to b's final text without losing a's own items
		expect(a.text()).toBe("second draft merged");
		expect(a.text()).toBe(b.text());
	});
});
