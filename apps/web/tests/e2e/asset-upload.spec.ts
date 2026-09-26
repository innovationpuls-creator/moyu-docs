import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "Str0ng#Pass123";

async function registerAccount(page: Page, email: string): Promise<void> {
	await page.goto("/register");
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(PASSWORD);
	await page.getByTestId("password-input").press("Enter");
	await expect(page).toHaveURL("/workspace");
}

test("uploads an attachment, inserts its text, and preserves it after reload", async ({
	page,
}) => {
	await registerAccount(page, `asset-${Date.now()}@example.com`);

	const workspaceKey = crypto.randomUUID();
	const workspace = await page.request.post("/v1/workspaces", {
		headers: { "Idempotency-Key": workspaceKey },
		data: { name: "Asset upload acceptance", idempotencyKey: workspaceKey },
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
				name: "Asset upload project",
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
			name: "Asset upload document",
			idempotencyKey: resourceKey,
		},
	});
	expect(resource.status()).toBe(201);
	const resourceId = (await resource.json()).resourceId as string;

	await page.goto(`/editor?resourceId=${resourceId}`);
	await expect(page.getByTestId("editor-rich-body")).toBeVisible();
	await expect(page.getByTestId("editor-presence")).toContainText(
		"实时协同已连接",
	);
	await page.getByTestId("editor-panel-tab-assets").click();
	await expect(page.getByTestId("asset-empty-state")).toBeVisible();

	const fileChooserPromise = page.waitForEvent("filechooser");
	await page.getByTestId("asset-upload-button").click();
	const fileChooser = await fileChooserPromise;
	await fileChooser.setFiles({
		name: "acceptance.txt",
		mimeType: "text/plain",
		buffer: Buffer.from("Synthetic browser upload fixture."),
	});

	await expect(page.getByText(/已上传并插入正文 1 个附件/)).toBeVisible();
	await expect(page.getByTestId("asset-list")).toContainText("acceptance.txt");
	await expect(page.getByTestId("editor-rich-body")).toContainText(
		"Synthetic browser upload fixture.",
	);

	await page.reload();
	await expect(page.getByTestId("editor-rich-body")).toContainText(
		"Synthetic browser upload fixture.",
	);
	await page.getByTestId("editor-panel-tab-assets").click();
	await expect(page.getByTestId("asset-list")).toContainText("acceptance.txt");
});
