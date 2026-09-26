import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "Str0ng#Pass123";

async function registerAccount(page: Page, email: string): Promise<void> {
	await page.goto("/register");
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(PASSWORD);
	await page.getByTestId("password-input").press("Enter");
	await expect(page).toHaveURL("/workspace");
}

async function createProject(
	page: Page,
	workspaceId: string,
	name: string,
): Promise<string> {
	const idempotencyKey = crypto.randomUUID();
	const response = await page.request.post(
		`/v1/workspaces/${workspaceId}/projects`,
		{
			headers: { "Idempotency-Key": idempotencyKey },
			data: { workspaceId, name, idempotencyKey },
		},
	);
	expect(response.status()).toBe(201);
	return (await response.json()).projectId as string;
}

async function createFolder(
	page: Page,
	projectId: string,
	name: string,
): Promise<{ folderId: string; resourceId: string }> {
	const folderKey = crypto.randomUUID();
	const folderResponse = await page.request.post(
		`/v1/projects/${projectId}/folders`,
		{
			headers: { "Idempotency-Key": folderKey },
			data: {
				projectId,
				parentFolderId: null,
				name,
				idempotencyKey: folderKey,
			},
		},
	);
	expect(folderResponse.status()).toBe(201);
	const folderId = (await folderResponse.json()).folderId as string;
	const resourceKey = crypto.randomUUID();
	const resourceResponse = await page.request.post("/v1/resources", {
		headers: { "Idempotency-Key": resourceKey },
		data: {
			projectId,
			folderId,
			resourceType: "document",
			name: `${name} resource`,
			idempotencyKey: resourceKey,
		},
	});
	expect(resourceResponse.status()).toBe(201);
	return {
		folderId,
		resourceId: (await resourceResponse.json()).resourceId as string,
	};
}

test("workspace cold load avoids duplicate and collapsed-folder resource queries", async ({
	page,
}) => {
	const email = `workspace-performance-${Date.now()}@example.com`;
	await registerAccount(page, email);

	const workspaceKey = crypto.randomUUID();
	const workspaceResponse = await page.request.post("/v1/workspaces", {
		headers: { "Idempotency-Key": workspaceKey },
		data: { name: "Workspace performance", idempotencyKey: workspaceKey },
	});
	expect(workspaceResponse.status()).toBe(201);
	const workspaceId = (await workspaceResponse.json()).workspaceId as string;
	const primaryProjectId = await createProject(
		page,
		workspaceId,
		"Primary project",
	);
	const collapsedProjectId = await createProject(
		page,
		workspaceId,
		"Collapsed project",
	);
	const primaryFolders = await Promise.all([
		createFolder(page, primaryProjectId, "Primary one"),
		createFolder(page, primaryProjectId, "Primary two"),
	]);
	const collapsedFolders = await Promise.all([
		createFolder(page, collapsedProjectId, "Collapsed one"),
		createFolder(page, collapsedProjectId, "Collapsed two"),
	]);

	const measurementPage = await page.context().newPage();
	const resourceRequests: Array<{
		projectId: string;
		folderId: string | null;
	}> = [];
	const projectTreeRequests: string[] = [];
	measurementPage.on("request", (request) => {
		if (request.method() !== "GET") return;
		const url = new URL(request.url());
		if (!url.pathname.startsWith("/v1/projects/")) return;
		const treeMatch = url.pathname.match(/^\/v1\/projects\/([^/]+)$/);
		if (treeMatch) {
			projectTreeRequests.push(treeMatch[1]);
			return;
		}
		const resourcesMatch = url.pathname.match(
			/^\/v1\/projects\/([^/]+)\/resources$/,
		);
		if (resourcesMatch) {
			resourceRequests.push({
				projectId: resourcesMatch[1],
				folderId: url.searchParams.get("folderId"),
			});
		}
	});

	try {
		await measurementPage.goto(
			`/workspace?workspaceId=${workspaceId}&projectId=${primaryProjectId}`,
		);
		await measurementPage.waitForLoadState("networkidle");
		await expect(
			measurementPage.getByTestId(
				`console-tree-folder-${primaryFolders[0].folderId}`,
			),
		).toBeVisible();

		const metrics = {
			projectTrees: projectTreeRequests.length,
			rootResourceLists: resourceRequests.filter(
				(request) => request.folderId === null,
			).length,
			folderResourceLists: resourceRequests.filter(
				(request) => request.folderId !== null,
			).length,
			resourceListsForCollapsedProject: resourceRequests.filter(
				(request) => request.projectId === collapsedProjectId,
			).length,
			totalTreeAndResourceRequests:
				projectTreeRequests.length + resourceRequests.length,
		};
		console.log(`workspace-performance ${JSON.stringify(metrics)}`);

		expect(metrics).toEqual({
			projectTrees: 2,
			rootResourceLists: 2,
			folderResourceLists: 2,
			resourceListsForCollapsedProject: 1,
			totalTreeAndResourceRequests: 6,
		});

		await measurementPage
			.getByRole("button", { name: "展开 Collapsed project" })
			.click();
		const collapsedFolder = measurementPage.getByTestId(
			`console-tree-folder-${collapsedFolders[0].folderId}`,
		);
		await expect(collapsedFolder).toBeVisible();
		await collapsedFolder
			.getByRole("button", { name: "展开 Collapsed one" })
			.click();
		await expect(
			measurementPage.getByTestId(
				`console-tree-resource-${collapsedFolders[0].resourceId}`,
			),
		).toBeVisible();
		await measurementPage.waitForLoadState("networkidle");
		expect(
			resourceRequests.filter(
				(request) => request.projectId === collapsedProjectId,
			).length,
		).toBe(3);
	} finally {
		await measurementPage.close();
	}
});
