import { describe, expect, it } from "vitest";

import { ContentNodeError } from "../src/index.js";
import type { ProseMirrorJson } from "../src/pm.js";
import { pmToYjsText, yjsTextToPm } from "../src/yjs_pm.js";

describe("yjs-prosemirror baseline binding", () => {
	it("projects a pm doc into the yjs text", () => {
		const pm: ProseMirrorJson = {
			type: "doc",
			content: [
				{
					type: "heading",
					attrs: { level: 1 },
					content: [{ type: "text", text: "标题" }],
				},
				{ type: "paragraph", content: [{ type: "text", text: "第一段" }] },
			],
		};
		expect(pmToYjsText(pm)).toBe("标题\n第一段");
	});

	it("wraps yjs text back into a single-paragraph pm doc", () => {
		const pm = yjsTextToPm("正文字符串");
		expect(pm.type).toBe("doc");
		expect(pm.content).toHaveLength(1);
		expect(pm.content?.[0]).toMatchObject({ type: "paragraph" });
		expect(pmToYjsText(pm)).toBe("正文字符串");
	});

	it("rejects non-string yjs text", () => {
		expect(() => yjsTextToPm(42 as never)).toThrowError(ContentNodeError);
	});
});
