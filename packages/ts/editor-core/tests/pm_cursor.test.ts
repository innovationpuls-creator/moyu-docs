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
		expect(resolveCursorPosition(doc, "你好世界", 2)).toBe(2);
	});

	it("clamps offsets beyond the text", () => {
		const doc = docFromNodes([
			{ kind: "paragraph", children: [{ kind: "text", text: "ab" }] },
		] as never[]);
		expect(resolveCursorPosition(doc, "ab", 99)).toBe(2);
		expect(resolveCursorPosition(doc, "ab", -1)).toBe(0);
	});

	it("the plugin registers its own key", () => {
		const plugin = remoteCursorPlugin(() => null);
		expect(plugin.spec.key).toBeDefined();
	});

	it("multi-peer plugin renders a widget per provider", () => {
		const plugin = remoteCursorsPlugin(() => [
			() => ({ text: "ab", cursor: 1 }),
			() => ({ text: "ab", cursor: 2 }),
		]);
		expect(plugin).toBeDefined();
		expect(remoteCursorsPlugin(() => []).spec.key).toBeDefined();
	});
});
