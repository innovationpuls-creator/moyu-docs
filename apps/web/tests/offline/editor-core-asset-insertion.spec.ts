import { expect, test } from "@playwright/test";

test("asset panel insertion updates the mounted editor and Yjs projection", async ({
	page,
}) => {
	await page.route(
		"**/v1/resources/asset-insertion-test-resource/assets",
		(route) =>
			route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({
					resourceId: "asset-insertion-test-resource",
					assets: [
						{
							assetId: "asset-mounted-image",
							originalName: "diagram.png",
							mime: "image/png",
							sizeBytes: 68,
							sha256: "test-hash",
							createdAt: "2026-09-25T00:00:00Z",
						},
					],
				}),
			}),
	);
	await page.route("**/v1/assets/asset-mounted-image", (route) =>
		route.fulfill({
			status: 200,
			contentType: "image/png",
			body: Buffer.from("test preview"),
		}),
	);
	await page.goto("/");
	await page.evaluate(async () => {
		const fixtureUrl = `${window.location.origin}/tests/fixtures/editor-core-asset-insertion.ts`;
		const fixture = await import(fixtureUrl);
		fixture.mountAssetPanelInsertion();
	});
	const insert = page.getByTestId("asset-insert-asset-mounted-image");
	await expect(insert).toBeVisible();
	await insert.click();
	await expect
		.poll(() =>
			page.evaluate(() => window.__assetInsertionHarness?.read().text ?? ""),
		)
		.toBe("现有正文\n![diagram.png](asset://asset-mounted-image)");
	const result = await page.evaluate(
		() => window.__assetInsertionHarness?.read() ?? null,
	);

	expect(result).not.toBeNull();
	expect(result?.wasFocusedAtMount).toBe(false);
	expect(result?.markup).toContain('data-asset-id="asset-mounted-image"');
	expect(result?.events).toContain(result?.text);
	expect(result?.peerText).toBe(result?.text);
	expect(result?.updateCount).toBeGreaterThan(0);
	expect(result?.focusedAfterInsertion).toBe(true);
	await page.evaluate(() => window.__assetInsertionHarness?.destroy());
});

test("direct asset insertion works before an editor has ever received focus", async ({
	page,
}) => {
	await page.goto("/");
	await page.evaluate(async () => {
		const fixtureUrl = `${window.location.origin}/tests/fixtures/editor-core-asset-insertion.ts`;
		const fixture = await import(fixtureUrl);
		fixture.mountUnfocusedEditorInsertion();
	});
	const before = await page.evaluate(
		() => window.__assetInsertionHarness?.read() ?? null,
	);
	expect(before?.wasFocusedAtMount).toBe(false);

	await page.evaluate(() => window.__assetInsertionHarness?.insertDirectly());
	await expect
		.poll(() =>
			page.evaluate(() => window.__assetInsertionHarness?.read().text ?? ""),
		)
		.toBe("现有正文\n![direct.png](asset://asset-direct-image)");
	const result = await page.evaluate(
		() => window.__assetInsertionHarness?.read() ?? null,
	);

	expect(result?.markup).toContain('data-asset-id="asset-direct-image"');
	expect(result?.events).toContain(result?.text);
	expect(result?.peerText).toBe(result?.text);
	expect(result?.updateCount).toBeGreaterThan(0);
	expect(result?.focusedAfterInsertion).toBe(true);
	await page.evaluate(() => window.__assetInsertionHarness?.destroy());
});
