import { describe, expect, it } from "vitest";

import {
	ContentNodeError,
	parseDoc,
	toText,
	validateNode,
} from "../src/index.js";

describe("content-node model", () => {
	it("parses a valid document and projects its text", () => {
		const doc = [
			{ kind: "heading", level: 1, children: [{ kind: "text", text: "标题" }] },
			{
				kind: "paragraph",
				children: [
					{ kind: "text", text: "正文 " },
					{ kind: "text", text: "重点", marks: ["bold"] },
				],
			},
			{
				kind: "list",
				children: [
					{ kind: "paragraph", children: [{ kind: "text", text: "条目" }] },
				],
			},
		];
		const nodes = parseDoc(doc);
		expect(nodes).toHaveLength(3);
		expect(toText(nodes)).toBe("标题\n正文 重点\n条目");
	});

	it("rejects unknown kinds", () => {
		expect(() => parseDoc([{ kind: "image", src: "x" }])).toThrowError(
			ContentNodeError,
		);
	});

	it("rejects invalid heading levels", () => {
		expect(() =>
			validateNode({ kind: "heading", level: 4, children: [] } as never),
		).toThrowError(ContentNodeError);
	});

	it("rejects non-text children of a paragraph", () => {
		expect(() =>
			validateNode({
				kind: "paragraph",
				children: [{ kind: "heading", level: 1 } as never],
			}),
		).toThrowError(ContentNodeError);
	});

	it("rejects list items that are not paragraphs", () => {
		expect(() =>
			validateNode({
				kind: "list",
				children: [{ kind: "text", text: "x" } as never],
			}),
		).toThrowError(ContentNodeError);
	});

	it("projects stable image and attachment asset references", () => {
		const nodes = parseDoc([
			{
				kind: "image",
				nodeId: "n_image-1",
				assetId: "asset-image-1",
				label: "diagram 1.png",
			},
			{
				kind: "attachment",
				nodeId: "n_file-1",
				assetId: "asset-file-1",
				label: "notes.txt",
			},
		]);

		expect(toText(nodes)).toBe(
			"![diagram 1.png](asset://asset-image-1)\n[notes.txt](asset://asset-file-1)",
		);
	});

	it("requires stable identity and asset IDs for references", () => {
		expect(() =>
			validateNode({
				kind: "image",
				assetId: "asset-image-1",
				label: "diagram.png",
			} as never),
		).toThrowError(ContentNodeError);
	});
});
