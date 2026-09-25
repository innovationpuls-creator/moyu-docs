import { expect, test } from "@playwright/test";

test("attachment retry reuses its key and a successful upload clears it", async ({
	page,
}) => {
	const uploadKeys: string[] = [];
	let postCount = 0;
	await page.route(
		"**/v1/resources/asset-upload-idempotency-resource/assets",
		async (route) => {
			if (route.request().method() === "GET") {
				await route.fulfill({
					status: 200,
					contentType: "application/json",
					body: JSON.stringify({
						resourceId: "asset-upload-idempotency-resource",
						assets: [],
					}),
				});
				return;
			}

			postCount += 1;
			uploadKeys.push((await route.request().allHeaders())["idempotency-key"]);
			if (postCount === 1) {
				await route.abort("failed");
				return;
			}
			await route.fulfill({
				status: 201,
				contentType: "application/json",
				body: JSON.stringify({
					assetId: `asset-${postCount}`,
					sha256: "a".repeat(64),
					sizeBytes: 11,
				}),
			});
		},
	);

	await page.goto("/login");
	await page.evaluate(async () => {
		const fixture = await import(
			`${window.location.origin}/tests/fixtures/asset-upload-idempotency.ts`
		);
		fixture.mountAssetsPanel();
	});
	const file = {
		name: "diagram.png",
		mimeType: "image/png",
		buffer: Buffer.from("image bytes"),
	};
	const input = page.getByTestId("asset-upload-input");
	await input.setInputFiles(file);
	await expect(page.getByTestId("asset-upload-retry-0")).toBeVisible();
	await page.getByTestId("asset-upload-retry-0").click();
	await expect(page.getByTestId("asset-upload-retry-0")).toHaveCount(0);

	await input.setInputFiles(file);
	await expect(page.getByTestId("asset-upload-retry-0")).toHaveCount(0);
	expect(uploadKeys).toHaveLength(3);
	expect(uploadKeys[0]).toBeTruthy();
	expect(uploadKeys[0]).toBe(uploadKeys[1]);
	expect(uploadKeys[2]).not.toBe(uploadKeys[1]);
	expect(uploadKeys[0]?.[14]).toBe("7");

	await page.evaluate(() => window.__assetsPanelHarness?.destroy());
});
