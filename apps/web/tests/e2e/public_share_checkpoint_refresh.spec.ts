import { createTextDocument } from "@dom/editor-core";
import { expect, test, type WebSocketRoute } from "@playwright/test";

function fullState(text: string): Uint8Array {
	const model = createTextDocument();
	model.setText(text);
	const update = model.exportState();
	model.destroy();
	return update;
}

function encodeSyncUpdate(
	resourceId: string,
	subscriptionId: string,
	update: Uint8Array,
): Uint8Array {
	const header = new TextEncoder().encode(
		JSON.stringify({
			protocolVersion: 1,
			frameType: "Sync",
			payloadKind: "binary",
			messageType: "sync.update",
			resourceId,
			subscriptionId,
		}),
	);
	const frame = new Uint8Array(6 + header.byteLength + update.byteLength);
	frame.set([0x44, 0x4d, 1, 1], 0);
	new DataView(frame.buffer).setUint16(4, header.byteLength, false);
	frame.set(header, 6);
	frame.set(update, 6 + header.byteLength);
	return frame;
}

test("public checkpoint refreshes safely and promotes to current Yjs state", async ({
	page,
}) => {
	const connections: Array<{
		socket: WebSocketRoute;
		resourceId: string;
		subscriptionId: string;
	}> = [];
	const snapshots = ["checkpoint one", "checkpoint two"];
	let snapshotReads = 0;
	await page.route("**/v1/public/shares/test-token", async (route) => {
		const text = snapshots[Math.min(snapshotReads, snapshots.length - 1)];
		snapshotReads += 1;
		if (snapshotReads === 2) {
			await new Promise((resolve) => setTimeout(resolve, 350));
		}
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				resourceId: "resource-share-1",
				name: "共享文档",
				resourceType: "document",
				snapshot: { text },
				journalSeq: snapshotReads,
			}),
		});
	});
	await page.routeWebSocket("**/public-share", (socket) => {
		const connection = {
			socket,
			resourceId: "",
			subscriptionId: "",
		};
		connections.push(connection);
		socket.onMessage((message) => {
			if (typeof message !== "string") return;
			const frame = JSON.parse(message) as Record<string, unknown>;
			if (frame.type === "authenticate-share") {
				socket.send(
					JSON.stringify({
						protocolVersion: 1,
						type: "share-authenticated",
						payload: { status: "ok" },
					}),
				);
			} else if (frame.type === "subscribe") {
				connection.resourceId = String(frame.resourceId);
				connection.subscriptionId = String(frame.subscriptionId);
				const stateKind = connections.length < 4 ? "checkpoint" : "yjs";
				socket.send(
					JSON.stringify({
						protocolVersion: 1,
						type: "share-state",
						resourceId: connection.resourceId,
						subscriptionId: connection.subscriptionId,
						payload: { stateKind },
					}),
				);
				if (stateKind === "yjs") {
					socket.send(
						Buffer.from(
							encodeSyncUpdate(
								connection.resourceId,
								connection.subscriptionId,
								fullState("current Yjs body"),
							),
						),
					);
				}
			}
		});
	});

	await page.goto("/share/test-token");
	const editor = page.getByTestId("public-share-content-editor");
	await expect(editor.locator(".ProseMirror")).toContainText("checkpoint one");
	await expect.poll(() => connections.length).toBe(1);

	const sendUpdate = (connectionIndex: number, text: string) => {
		const connection = connections[connectionIndex];
		connection.socket.send(
			Buffer.from(
				encodeSyncUpdate(
					connection.resourceId,
					connection.subscriptionId,
					fullState(text),
				),
			),
		);
	};
	await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
	sendUpdate(0, "must not merge checkpoint with delta");
	await expect.poll(() => connections.length).toBe(2);
	await expect(editor.locator(".ProseMirror")).not.toContainText(
		"must not merge checkpoint with delta",
	);
	await expect.poll(() => connections[1]?.subscriptionId).not.toBe("");
	await expect.poll(() => snapshotReads).toBe(2);
	sendUpdate(1, "candidate delta is also only a refresh signal");
	await expect.poll(() => connections.length).toBe(3);
	await expect(editor.locator(".ProseMirror")).toContainText("checkpoint two");
	await expect(editor.locator(".ProseMirror")).not.toContainText(
		"candidate delta is also only a refresh signal",
	);

	sendUpdate(0, "signal checkpoint to Yjs transition");
	await expect.poll(() => connections.length).toBe(4);
	await expect(editor.locator(".ProseMirror")).toContainText(
		"current Yjs body",
	);
	await expect(editor.locator(".ProseMirror")).not.toContainText(
		"checkpoint two",
	);
});
