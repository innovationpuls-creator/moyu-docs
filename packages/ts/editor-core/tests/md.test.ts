import { describe, expect, it } from "vitest";
import { toText } from "../src/index.js";
import { markdownToNodes, nodesToMarkdown } from "../src/md.js";

describe("markdown projection", () => {
	it("exports blocks with headings, paragraphs, lists and marks", () => {
		const nodes = [
			{ kind: "heading", level: 1, children: [{ kind: "text", text: "标题" }] },
			{
				kind: "paragraph",
				children: [{ kind: "text", text: "重点", marks: ["bold"] }],
			},
			{
				kind: "list",
				children: [
					{ kind: "paragraph", children: [{ kind: "text", text: "A" }] },
				],
			},
		] as never[];
		expect(nodesToMarkdown(nodes)).toBe("# 标题\n**重点**\n- A");
	});

	it("parses a bounded markdown document back into nodes", () => {
		const nodes = markdownToNodes("# 标题\n**重点**\n- 条目");
		expect(nodes).toHaveLength(3);
		expect(nodes[0].kind).toBe("heading");
		expect(nodes[1].kind).toBe("paragraph");
		const firstText = (nodes[1] as { children?: Array<{ marks?: string[] }> })
			.children?.[0];
		expect(firstText?.marks).toContain("bold");
		expect(toText(nodes)).toBe("标题\n重点\n条目");
	});

	it("degrades unsupported syntax to plain text (never throws)", () => {
		expect(() => markdownToNodes("[link](x)")).not.toThrowError();
		const nodes = markdownToNodes("[link](x)");
		expect(nodes[0].kind).toBe("paragraph");
	});

	it("round-trips a simple document", () => {
		const md = "# 主题\n正文段落\n";
		expect(nodesToMarkdown(markdownToNodes(md))).toBe("# 主题\n正文段落");
	});
});
