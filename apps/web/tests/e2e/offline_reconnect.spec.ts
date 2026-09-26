import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "Str0ng#Pass123";

async function register(page: Page, email: string): Promise<void> {
	await page.goto("/register");
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(PASSWORD);
	await page.getByTestId("password-input").press("Enter");
	await expect(page).toHaveURL("/workspace");
}

async function login(page: Page, email: string): Promise<void> {
	await page.goto("/login");
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(PASSWORD);
	await page.getByTestId("password-input").press("Enter");
	await expect(page).toHaveURL("/workspace");
}

async function createResource(page: Page): Promise<string> {
	const workspaceKey = crypto.randomUUID();
	const workspace = await page.request.post("/v1/workspaces", {
		headers: { "Idempotency-Key": workspaceKey },
		data: { name: "离线恢复验收", idempotencyKey: workspaceKey },
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
				name: "离线恢复项目",
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
			resourceType: "document",
			name: "离线并发文档",
			idempotencyKey: resourceKey,
		},
	});
	expect(resource.status()).toBe(201);
	return (await resource.json()).resourceId as string;
}

async function fillEditor(page: Page, value: string): Promise<void> {
	const source = page.getByTestId("editor-draft-textarea");
	if (!(await source.isVisible())) {
		await page.getByTestId("editor-rich-toggle").click();
	}
	await source.fill(value);
}

test("offline edits survive refresh and converge with a concurrent online edit", async ({
	browser,
}) => {
	const email = `e2e-offline-${Date.now()}-${crypto.randomUUID()}@example.com`;
	const seedContext = await browser.newContext();
	const contextA = await browser.newContext();
	const contextB = await browser.newContext();
	try {
		await register(await seedContext.newPage(), email);
		const pageA = await contextA.newPage();
		await login(pageA, email);
		const pageB = await contextB.newPage();
		await login(pageB, email);

		const resourceId = await createResource(pageA);
		await pageA.goto(`/editor?resourceId=${resourceId}`);
		await pageB.goto(`/editor?resourceId=${resourceId}`);
		await expect(pageA.getByTestId("realtime-status")).toHaveText("connected", {
			timeout: 10_000,
		});
		await expect(pageB.getByTestId("realtime-status")).toHaveText("connected", {
			timeout: 10_000,
		});

		await contextA.setOffline(true);
		await fillEditor(pageA, "离线端保留的修改");
		await expect(pageA.getByTestId("editor-offline-status")).toContainText(
			"离线内容将在重新验证会话后同步",
			{ timeout: 10_000 },
		);
		await pageA.getByTestId("editor-save").click();
		await expect(pageA.getByTestId("editor-save-status")).toHaveText(
			"已保存在此设备。",
		);

		await fillEditor(pageB, "在线端并发提交的修改");
		await expect(pageB.getByTestId("editor-offline-status")).toContainText(
			"持久保存",
			{ timeout: 15_000 },
		);

		await contextA.setOffline(false);
		await expect(pageA.getByTestId("editor-draft-textarea")).toHaveValue(
			/离线端保留的修改/,
			{ timeout: 15_000 },
		);
		await expect(pageA.getByTestId("editor-draft-textarea")).toHaveValue(
			/在线端并发提交的修改/,
			{ timeout: 15_000 },
		);
		await expect(pageA.getByTestId("editor-offline-status")).toContainText(
			"持久保存",
			{ timeout: 15_000 },
		);
		await expect(pageB.getByTestId("editor-draft-textarea")).toHaveValue(
			/离线端保留的修改/,
			{ timeout: 15_000 },
		);

		await contextA.setOffline(true);
		const recoveredText = await pageA
			.getByTestId("editor-draft-textarea")
			.inputValue();
		await pageA
			.getByTestId("editor-draft-textarea")
			.pressSequentially(" + 刷新前草稿");
		await expect(pageA.getByTestId("editor-offline-status")).toContainText(
			"离线内容将在重新验证会话后同步",
			{ timeout: 10_000 },
		);
		await pageA.reload();
		await expect(pageA.getByTestId("editor-draft-textarea")).toHaveValue(
			`${recoveredText} + 刷新前草稿`,
			{ timeout: 10_000 },
		);
		await contextA.setOffline(false);
		await expect(pageB.getByTestId("editor-draft-textarea")).toHaveValue(
			/刷新前草稿/,
			{ timeout: 15_000 },
		);
	} finally {
		await contextA.close();
		await contextB.close();
		await seedContext.close();
	}
});
