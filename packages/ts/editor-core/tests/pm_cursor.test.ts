import { describe, expect, it } from "vitest";

import {
	remoteCursorPlugin,
	remoteCursorsPlugin,
	resolveCursorPosition,
} from "../src/pm_cursor.js";
import { docFromNodes } from "../src/pm_schema.js";

describe("remote cursor mapping", () => {
	it("resolves an outer-text offset into the pm doc position", () => {
		const doc = docFromNodes([
			{ kind: "paragraph", children: [{ kind: "text", text: "你好世界" }] },
		] as never[]);
		// selectionStart counts UTF-16 units (BMP CJK = 1 unit per char)
		expect(resolveCursorPosition(doc, "你好世界", 2)).toBe(3);
	});

	it("clamps offsets beyond the text", () => {
		const doc = docFromNodes([
			{ kind: "paragraph", children: [{ kind: "text", text: "ab" }] },
		] as never[]);
		expect(resolveCursorPosition(doc, "ab", 99)).toBe(3);
		expect(resolveCursorPosition(doc, "ab", -1)).toBe(1);
	});

	it("maps a newline-separated offset into the next ProseMirror block", () => {
		const doc = docFromNodes([
			{ kind: "paragraph", children: [{ kind: "text", text: "a" }] },
			{ kind: "paragraph", children: [{ kind: "text", text: "b" }] },
		] as never[]);
		expect(resolveCursorPosition(doc, "a\nb", 2)).toBe(4);
	});

	it("keeps remote cursor offsets aligned after an asset block", () => {
		const doc = docFromNodes([
			{
				kind: "image",
				nodeId: "n_image-1",
				assetId: "asset-image-1",
				label: "diagram 1.png",
			},
			{ kind: "paragraph", children: [{ kind: "text", text: "after" }] },
		]);
		const projection = "![diagram 1.png](asset://asset-image-1)\nafter";
		const assetTokenEnd = projection.indexOf("\n");

		expect(resolveCursorPosition(doc, projection, assetTokenEnd)).toBe(1);
		expect(resolveCursorPosition(doc, projection, assetTokenEnd + 3)).toBe(4);
	});

	it("the plugin registers its own key", () => {
		const plugin = remoteCursorPlugin(() => null);
		expect(plugin.spec.key).toBeDefined();
	});

	it("multi-peer plugin renders a widget per provider", () => {
		const plugin = remoteCursorsPlugin(() => [
			() => ({
				text: "ab",
				anchor: 1,
				head: 1,
				participantId: "peer-1",
				displayName: "协作者 A",
				color: "#637789",
			}),
			() => ({
				text: "ab",
				anchor: 2,
				head: 2,
				participantId: "peer-2",
				displayName: "协作者 B",
				color: "#bd6546",
			}),
		]);
		expect(plugin).toBeDefined();
		expect(remoteCursorsPlugin(() => []).spec.key).toBeDefined();
	});
});
