import { describe, expect, it } from "vitest";
import {
	decodeRealtimeBinaryFrame,
	encodeRealtimeBinaryFrame,
} from "../src/index.js";

describe("realtime binary frame", () => {
	it("round trips binary updates with stable routing references", () => {
		const payload = new Uint8Array([0, 255, 1, 128]);
		const frame = encodeRealtimeBinaryFrame(
			{
				messageType: "sync.update",
				resourceId: "resource-1",
				subscriptionId: "subscription-1",
			},
			payload,
		);
		const decoded = decodeRealtimeBinaryFrame(frame);

		expect(decoded.header.frameType).toBe("Sync");
		expect(decoded.header.payloadKind).toBe("binary");
		expect(decoded.header.messageType).toBe("sync.update");
		expect(decoded.header.resourceId).toBe("resource-1");
		expect(decoded.header.subscriptionId).toBe("subscription-1");
		expect(decoded.payload).toEqual(payload);
	});

	it("rejects unsupported and truncated frames", () => {
		expect(() =>
			decodeRealtimeBinaryFrame(new Uint8Array([0, 0, 1])),
		).toThrow();
		const frame = encodeRealtimeBinaryFrame(
			{
				messageType: "sync.state-vector",
				resourceId: "resource-1",
				subscriptionId: "subscription-1",
			},
			new Uint8Array([1]),
		);
		frame[2] = 2;
		expect(() => decodeRealtimeBinaryFrame(frame)).toThrow(/Unsupported/);
	});
});
