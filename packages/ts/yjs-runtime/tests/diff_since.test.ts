import { describe, expect, it } from "vitest";

import { createDocument, diffSince, setText, stateVector } from "../src/index";

describe("state-vector incremental sync", () => {
	it("diffSince from a stale vector replays exactly the missing tail", () => {
		const a = createDocument();
		setText(a, "标题");
		const stale = stateVector(a);
		const preEditState = a.exportState();
		setText(a, "标题\n追加");
		const tail = diffSince(a, stale);
		// a replica at the pre-edit state plus the tail converges fully
		const b = createDocument();
		b.applyRemoteUpdate(preEditState);
		b.applyRemoteUpdate(tail);
		expect(b.text()).toBe("标题\n追加");
	});

	it("a replica already caught up merges an empty diff without change", () => {
		const a = createDocument();
		setText(a, "一致的内容");
		const vector = stateVector(a);
		const empty = diffSince(a, vector);
		const b = createDocument();
		b.applyRemoteUpdate(a.exportState());
		b.applyRemoteUpdate(empty);
		expect(b.text()).toBe("一致的内容");
	});
});
