import { describe, expect, it } from "vitest";

import { ContentNodeError } from "../src/index.js";
import { fromProseMirror, toProseMirror } from "../src/pm.js";

describe("ProseMirror adapter", () => {
	it("maps canonical nodes to a pm doc and back", () => {
		const nodes = [
			{
				kind: "heading",
				level: 2,
				children: [{ kind: "text", text: "小标题" }],
			},
			{
				kind: "paragraph",
				children: [
					{ kind: "text", text: "正文" },
					{ kind: "text", text: "加粗", marks: ["bold"] },
				],
			},
		] as never[];
		const pm = toProseMirror(nodes);
		expect(pm.type).toBe("doc");
		expect(pm.content?.[0]).toMatchObject({
			type: "heading",
			attrs: { level: 2 },
		});
		const round = fromProseMirror(pm);
		expect(round).toHaveLength(2);
		expect(round[1].kind).toBe("paragraph");
	});

	it("marks map to PM mark names", () => {
		const pm = toProseMirror([
			{
				kind: "text",
				text: "x",
				marks: ["bold", "italic"],
			},
		] as never[]);
		expect(pm.content?.[0]).toMatchObject({
			marks: [{ type: "strong" }, { type: "em" }],
		});
	});

	it("rejects unknown PM node types on the way in", () => {
		expect(() =>
			fromProseMirror({
				type: "doc",
				content: [{ type: "image", src: "x" }],
			}),
		).toThrowError(ContentNodeError);
	});

	it("maps bulletList to list nodes", () => {
		const pm = toProseMirror([
			{
				kind: "list",
				children: [
					{
						kind: "paragraph",
						children: [{ kind: "text", text: "条目" }],
					},
				],
			},
		] as never[]);
		expect(pm.content?.[0].type).toBe("bulletList");
		const back = fromProseMirror(pm);
		expect(back[0].kind).toBe("list");
	});
});
