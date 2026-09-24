import { describe, expect, it } from "vitest";

import { docFromNodes, nodesFromDoc, textContent } from "../src/pm_schema.js";

describe("prosemirror-model grounding", () => {
	it("validates canonical nodes into a PM doc and back", () => {
		const nodes = [
			{ kind: "heading", level: 2, children: [{ kind: "text", text: "标题" }] },
			{
				kind: "paragraph",
				children: [
					{ kind: "text", text: "正文 " },
					{ kind: "text", text: "加粗", marks: ["bold"] },
				],
			},
		] as never[];
		const doc = docFromNodes(nodes);
		// PM textContent concatenates blocks; the canonical toText()
		// projection already supplies the newline-joined form via the adapter
		expect(textContent(doc)).toBe("标题正文 加粗");
		const back = nodesFromDoc(doc);
		expect(back).toHaveLength(2);
		expect(back[1].kind).toBe("paragraph");
	});

	it("registers the schema so unknown structures are rejected", () => {
		expect(() =>
			docFromNodes([{ kind: "image", src: "x" }] as never),
		).toThrowError();
	});

	it("round-trips a bullet list through the schema", () => {
		const nodes = [
			{
				kind: "list",
				children: [
					{ kind: "paragraph", children: [{ kind: "text", text: "A" }] },
					{ kind: "paragraph", children: [{ kind: "text", text: "B" }] },
				],
			},
		] as never[];
		const doc = docFromNodes(nodes);
		expect(textContent(doc)).toBe("AB");
		const json = doc.toJSON();
		const content = json.content ?? [];
		expect((content[0] as { type?: string }).type).toBe("bulletList");
	});
});
