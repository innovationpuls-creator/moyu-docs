import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "Str0ng#Pass123";

async function registerAccount(page: Page, email: string): Promise<void> {
	await page.goto("/register");
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(PASSWORD);
	await page.getByTestId("password-input").press("Enter");
	await expect(page).toHaveURL("/workspace");
}

test("folder resources expand, list at their folder, and open by stable ID", async ({
	page,
}) => {
	const email = `folder-${Date.now()}@example.com`;
	await registerAccount(page, email);

	const workspaceKey = crypto.randomUUID();
	const workspace = await page.request.post("/v1/workspaces", {
		headers: { "Idempotency-Key": workspaceKey },
		data: { name: "Folder workspace", idempotencyKey: workspaceKey },
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
				name: "Folder project",
				idempotencyKey: projectKey,
			},
		},
	);
	expect(project.status()).toBe(201);
	const projectId = (await project.json()).projectId as string;

	const folderKey = crypto.randomUUID();
	const folder = await page.request.post(`/v1/projects/${projectId}/folders`, {
		headers: { "Idempotency-Key": folderKey },
		data: {
			projectId,
			parentFolderId: null,
			name: "Specifications",
			idempotencyKey: folderKey,
		},
	});
	expect(folder.status()).toBe(201);
	const folderId = (await folder.json()).folderId as string;

	const resourceKey = crypto.randomUUID();
	const resource = await page.request.post("/v1/resources", {
		headers: { "Idempotency-Key": resourceKey },
		data: {
			projectId,
			folderId,
			resourceType: "markdown",
			name: "Folder notes",
			idempotencyKey: resourceKey,
		},
	});
	expect(resource.status()).toBe(201);
	const resourceId = (await resource.json()).resourceId as string;

	await page.goto(
		`/workspace?workspaceId=${workspaceId}&projectId=${projectId}`,
	);
	await page.getByTestId("console-notifications").click();
	await expect(page.getByRole("dialog", { name: "通知" })).toContainText(
		"暂时没有通知。",
	);

	await page.keyboard.press("Control+k");
	const searchDialog = page.getByRole("dialog", { name: "搜索工作区资源" });
	await expect(searchDialog).toBeVisible();
	const searchInput = page.getByRole("textbox", { name: "搜索名称或正文" });
	await searchInput.fill("Folder notes");
	const searchResult = searchDialog.getByRole("button").filter({
		hasText: "Folder notes",
	});
	await expect(searchResult).toBeVisible();
	await searchInput.press("Enter");
	await expect(page).toHaveURL(
		new RegExp(`/editor\\?resourceId=${resourceId}`),
	);
	await expect(page.getByTestId("editor-breadcrumb")).toContainText(
		"Specifications",
	);
	await page.getByTestId("editor-back").click();

	const folderNode = page.getByTestId(`console-tree-folder-${folderId}`);
	await expect(folderNode).toBeVisible();
	await folderNode.getByRole("button", { name: "展开 Specifications" }).click();
	await expect(
		page.getByTestId(`console-tree-resource-${resourceId}`),
	).toBeVisible();
	await folderNode
		.getByRole("button", { name: "Specifications", exact: true })
		.click();

	const resourceRow = page.getByTestId("console-resource-row");
	await expect(resourceRow).toContainText("Folder notes");
	await resourceRow.click();
	await expect(page.getByTestId("resource-name-input")).toHaveValue(
		"Folder notes",
	);
	await expect(page).toHaveURL(
		new RegExp(`/editor\\?resourceId=${resourceId}`),
	);
	await page.getByTestId("editor-trash").click();
	await expect(page).toHaveURL(
		new RegExp(`/workspace\\?workspaceId=${workspaceId}&view=trash`),
	);
	const trashedResource = page
		.getByTestId("console-resource-row")
		.filter({ hasText: "Folder notes" });
	await expect(trashedResource).toBeVisible();
	await page.getByTestId(`trash-restore-${resourceId}`).click();
	await expect(trashedResource).toBeHidden();

	await page.goto(
		`/workspace?workspaceId=${workspaceId}&projectId=${projectId}&folderId=${folderId}`,
	);
	await expect(
		page.getByTestId("console-resource-row").filter({
			hasText: "Folder notes",
		}),
	).toBeVisible();
});
