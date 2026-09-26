import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "Str0ng#Pass123";

async function registerAccount(page: Page, email: string): Promise<void> {
	await page.goto("/register");
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(PASSWORD);
	await page.getByTestId("password-input").press("Enter");
	await expect(page).toHaveURL("/workspace");
}

test("rejects malformed and unsupported import JSON in the browser", async ({
	page,
}, testInfo) => {
	await registerAccount(page, `import-export-${Date.now()}@example.com`);

	const workspaceKey = crypto.randomUUID();
	const workspace = await page.request.post("/v1/workspaces", {
		headers: { "Idempotency-Key": workspaceKey },
		data: {
			name: "Import validation acceptance",
			idempotencyKey: workspaceKey,
		},
	});
	expect(workspace.status()).toBe(201);
	const workspaceId = (await workspace.json()).workspaceId as string;

	const projectKey = crypto.randomUUID();
	const project = await page.request.post(
		`/v1/workspaces/${workspaceId}/projects`,
		{
			headers: { "Idempotency-Key": projectKey },
			data: {
				workspaceId,
				name: "Import validation project",
				idempotencyKey: projectKey,
			},
		},
	);
	expect(project.status()).toBe(201);
	const projectId = (await project.json()).projectId as string;

	const resourceKey = crypto.randomUUID();
	const resource = await page.request.post("/v1/resources", {
		headers: { "Idempotency-Key": resourceKey },
		data: {
			projectId,
			resourceType: "markdown",
			name: "Import validation document",
			idempotencyKey: resourceKey,
		},
	});
	expect(resource.status()).toBe(201);
	const resourceId = (await resource.json()).resourceId as string;

	const importRequests: string[] = [];
	page.on("request", (request) => {
		if (
			request.method() === "POST" &&
			request.url().includes(`/v1/resources/${resourceId}/import`)
		) {
			importRequests.push(request.url());
		}
	});

	await page.goto(`/editor?resourceId=${resourceId}`);
	await expect(page.getByTestId("editor-rich-body")).toBeVisible();
	await page.getByTestId("editor-panel-tab-importexport").click();
	const input = page.getByTestId("resource-import-input");

	await input.setInputFiles({
		name: "malformed.json",
		mimeType: "application/json",
		buffer: Buffer.from("{"),
	});
	await expect(page.getByRole("status")).toHaveText(
		"文件不是有效的 JSON 文档。",
	);

	await input.setInputFiles({
		name: "unsupported.json",
		mimeType: "application/json",
		buffer: Buffer.from(JSON.stringify({ kind: "not-a-dom-document" })),
	});
	await expect(page.getByRole("status")).toHaveText(
		"文件不是 DOM 文档导出格式。",
	);
	expect(importRequests).toHaveLength(0);
	await page.screenshot({
		path: testInfo.outputPath("import-validation.png"),
		fullPage: true,
	});
});
