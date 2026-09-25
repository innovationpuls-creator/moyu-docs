import { expect, test } from "@playwright/test";

const failedTaskId = "00000000-0000-0000-0000-000000000001";

function taskSummary(
	taskId: string,
	state: "Failed" | "Succeeded" | "Queued" = "Succeeded",
) {
	return {
		taskId,
		taskType: "history.restore",
		state,
		stage: null,
		messageCode: null,
		current: null,
		total: null,
		percentage: null,
		updatedAt: "2026-09-25T00:00:00Z",
		retryCount: 0,
		retryOfTaskId: null,
		cancelRequestedAt: null,
		queuedAt: "2026-09-25T00:00:00Z",
		startedAt: null,
		finishedAt:
			state === "Failed" || state === "Succeeded"
				? "2026-09-25T00:00:00Z"
				: null,
		failureCode: state === "Failed" ? "RESTORE_FAILED" : null,
	};
}

async function mockCurrentAccount(page: import("@playwright/test").Page) {
	await page.route("**/v1/auth/me", (route) =>
		route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				accountId: "00000000-0000-0000-0000-000000000010",
				primaryEmail: "task-center@example.com",
			}),
		}),
	);
}

async function mockFailedTaskList(
	page: import("@playwright/test").Page,
	onRetryRequest: () => void,
) {
	await mockCurrentAccount(page);
	await page.route("**/v1/tasks**", async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (request.method() === "GET" && url.pathname === "/v1/tasks") {
			await route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({
					tasks: [taskSummary(failedTaskId, "Failed")],
					limit: 50,
					offset: 0,
				}),
			});
			return;
		}
		if (request.method() === "POST" && url.pathname.endsWith("/retry")) {
			onRetryRequest();
			await route.fulfill({
				status: 201,
				contentType: "application/json",
				body: JSON.stringify({
					task: taskSummary("00000000-0000-0000-0000-000000000002", "Queued"),
				}),
			});
			return;
		}
		await route.abort();
	});
}

test("retry reuses its saved key after reload and clears it after success", async ({
	page,
}) => {
	await mockCurrentAccount(page);
	const retryKeys: string[] = [];
	await page.route("**/v1/tasks**", async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (request.method() === "GET" && url.pathname === "/v1/tasks") {
			await route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({
					tasks: [taskSummary(failedTaskId, "Failed")],
					limit: 50,
					offset: Number(url.searchParams.get("offset") ?? 0),
				}),
			});
			return;
		}
		if (request.method() === "POST" && url.pathname.endsWith("/retry")) {
			retryKeys.push(request.headers()["idempotency-key"] ?? "");
			if (retryKeys.length === 1) {
				// The server may already have accepted the retry before the client
				// loses the response. A second click must replay the same key.
				await route.abort("failed");
				return;
			}
			await route.fulfill({
				status: 201,
				contentType: "application/json",
				body: JSON.stringify({
					task: taskSummary("00000000-0000-0000-0000-000000000002", "Queued"),
				}),
			});
			return;
		}
		await route.abort();
	});

	await page.goto("/tasks");
	const retryButton = page.getByRole("button", { name: "重试任务" });
	await expect(retryButton).toBeVisible();
	await retryButton.click();
	await expect(page.getByRole("alert")).toBeVisible();
	await expect.poll(() => retryKeys).toHaveLength(1);
	await page.reload();
	const retryButtonAfterReload = page.getByRole("button", { name: "重试任务" });
	await expect(retryButtonAfterReload).toBeVisible();
	await retryButtonAfterReload.click();
	await expect.poll(() => retryKeys).toHaveLength(2);
	await expect.poll(() => retryButtonAfterReload.isEnabled()).toBe(true);
	await retryButtonAfterReload.click();
	await expect.poll(() => retryKeys).toHaveLength(3);

	expect(retryKeys[0]).toBeTruthy();
	expect(retryKeys[1]).toBe(retryKeys[0]);
	expect(retryKeys[2]).not.toBe(retryKeys[1]);
});

test("429 retry reuses its key after reload", async ({ page }) => {
	await mockCurrentAccount(page);
	const retryKeys: string[] = [];
	await page.route("**/v1/tasks**", async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (request.method() === "GET" && url.pathname === "/v1/tasks") {
			await route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({
					tasks: [taskSummary(failedTaskId, "Failed")],
					limit: 50,
					offset: 0,
				}),
			});
			return;
		}
		if (request.method() === "POST" && url.pathname.endsWith("/retry")) {
			retryKeys.push(request.headers()["idempotency-key"] ?? "");
			if (retryKeys.length === 1) {
				await route.fulfill({
					status: 429,
					contentType: "application/json",
					body: JSON.stringify({
						category: "RateLimit",
						errorCode: "RATE_LIMITED",
						messageKey: "auth.error.rateLimited",
						message: "Request rate limited",
						retryable: true,
						requestId: "00000000-0000-0000-0000-000000000099",
					}),
				});
				return;
			}
			await route.fulfill({
				status: 201,
				contentType: "application/json",
				body: JSON.stringify({
					task: taskSummary("00000000-0000-0000-0000-000000000002", "Queued"),
				}),
			});
			return;
		}
		await route.abort();
	});

	await page.goto("/tasks");
	const retryButton = page.getByRole("button", { name: "重试任务" });
	await expect(retryButton).toBeVisible();
	await retryButton.click();
	await expect(page.getByRole("alert")).toBeVisible();
	await expect.poll(() => retryKeys).toHaveLength(1);
	await page.reload();
	const retryButtonAfterReload = page.getByRole("button", { name: "重试任务" });
	await expect(retryButtonAfterReload).toBeVisible();
	await retryButtonAfterReload.click();
	await expect.poll(() => retryKeys).toHaveLength(2);
	await expect.poll(() => retryButtonAfterReload.isEnabled()).toBe(true);
	await retryButtonAfterReload.click();
	await expect.poll(() => retryKeys).toHaveLength(3);

	expect(retryKeys[0]).toBeTruthy();
	expect(retryKeys[1]).toBe(retryKeys[0]);
	expect(retryKeys[2]).not.toBe(retryKeys[1]);
});

for (const { operation, expectedMessage } of [
	{
		operation: "read",
		expectedMessage: "无法读取浏览器会话中的重试记录",
	},
	{
		operation: "write",
		expectedMessage: "无法保存浏览器会话中的重试记录",
	},
	{
		operation: "remove",
		expectedMessage: "重试已提交，但无法清除浏览器中的待处理记录",
	},
] as const) {
	test(`reports session storage ${operation} failures explicitly`, async ({
		page,
	}) => {
		await page.addInitScript((storageOperation) => {
			if (storageOperation === "read") {
				Object.defineProperty(window, "sessionStorage", {
					configurable: true,
					get() {
						throw new DOMException("Blocked", "SecurityError");
					},
				});
				return;
			}
			if (storageOperation === "write") {
				const originalSetItem = Storage.prototype.setItem;
				Storage.prototype.setItem = function (key, value) {
					if (key.startsWith("dom:task-center:retry:")) {
						throw new DOMException("Blocked", "SecurityError");
					}
					originalSetItem.call(this, key, value);
				};
				return;
			}
			const originalRemoveItem = Storage.prototype.removeItem;
			Storage.prototype.removeItem = function (key) {
				if (key.startsWith("dom:task-center:retry:")) {
					throw new DOMException("Blocked", "SecurityError");
				}
				originalRemoveItem.call(this, key);
			};
		}, operation);
		let retryRequests = 0;
		await mockFailedTaskList(page, () => {
			retryRequests += 1;
		});

		await page.goto("/tasks");
		await page.getByRole("button", { name: "重试任务" }).click();
		await expect(page.getByRole("alert")).toContainText(expectedMessage);
		expect(retryRequests).toBe(operation === "remove" ? 1 : 0);
	});
}

test("load more preserves loaded tasks and shows loading/error state", async ({
	page,
}) => {
	await mockCurrentAccount(page);
	let offsetFiftyRequests = 0;
	let notifySecondPageStarted!: () => void;
	let releaseSecondPage!: () => void;
	const secondPageStarted = new Promise<void>((resolve) => {
		notifySecondPageStarted = resolve;
	});
	const secondPageGate = new Promise<void>((resolve) => {
		releaseSecondPage = resolve;
	});

	await page.route("**/v1/tasks**", async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (request.method() !== "GET" || url.pathname !== "/v1/tasks") {
			await route.abort();
			return;
		}
		const offset = Number(url.searchParams.get("offset") ?? 0);
		if (offset === 50) {
			offsetFiftyRequests += 1;
			if (offsetFiftyRequests <= 2) {
				if (offsetFiftyRequests === 1) {
					notifySecondPageStarted();
					await secondPageGate;
				}
				await route.fulfill({
					status: 503,
					contentType: "application/json",
					body: JSON.stringify({ errorCode: "TEMPORARY_UNAVAILABLE" }),
				});
				return;
			}
			const nextTasks = Array.from({ length: 10 }, (_, index) =>
				taskSummary(
					`00000000-0000-0000-0000-${String(index + 51).padStart(12, "0")}`,
				),
			);
			await route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify({ tasks: nextTasks, limit: 50, offset }),
			});
			return;
		}
		const firstTasks = Array.from({ length: 50 }, (_, index) =>
			taskSummary(
				`00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
			),
		);
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({ tasks: firstTasks, limit: 50, offset }),
		});
	});

	await page.goto("/tasks");
	const taskCards = page.getByTestId("task-card");
	await expect(taskCards).toHaveCount(50);
	await page.getByRole("button", { name: "加载更多" }).click();
	await secondPageStarted;
	await expect(
		page.getByRole("button", { name: "正在加载更多…" }),
	).toBeDisabled();
	await expect(taskCards).toHaveCount(50);

	releaseSecondPage();
	await expect.poll(() => offsetFiftyRequests).toBe(2);
	await expect(page.getByRole("alert")).toContainText("更多任务暂时无法加载");
	await expect(taskCards).toHaveCount(50);
	await page.getByRole("button", { name: "重试加载更多" }).click();
	await expect(taskCards).toHaveCount(60);
	await expect(page.getByRole("button", { name: "加载更多" })).toHaveCount(0);
	await expect.poll(() => offsetFiftyRequests).toBe(3);
});
