import { DomClient } from "@dom/client-sdk";
import { expect, test } from "@playwright/test";
import type { CommentThreadStatusControl } from "../../src/components/comment-thread-status";

interface ThreadStatusHarnessWindow extends Window {
	__threadStatusControl?: CommentThreadStatusControl;
	__threadStatusCalls?: string[];
}

test("comment thread status control returns server state and exposes reply gating", async ({
	page,
}) => {
	await page.goto("/login");
	await page.evaluate(async () => {
		const moduleUrl = new URL(
			"/src/components/comment-thread-status.ts",
			window.location.origin,
		).href;
		const { createCommentThreadStatusControl } = await import(moduleUrl);
		const calls: string[] = [];
		const client = {
			async resolveCommentThread(resourceId: string, threadId: string) {
				calls.push(`resolve:${resourceId}:${threadId}`);
				return {
					resourceId,
					threadId,
					status: "Resolved" as const,
					resolvedAt: "2026-09-25T00:00:00Z",
					resolvedBy: "actor",
				};
			},
			async reopenCommentThread(resourceId: string, threadId: string) {
				calls.push(`reopen:${resourceId}:${threadId}`);
				return {
					resourceId,
					threadId,
					status: "Open" as const,
					resolvedAt: null,
					resolvedBy: null,
				};
			},
		};
		const control = createCommentThreadStatusControl({
			resourceId: "resource-1",
			threadId: "thread-1",
			status: "Open",
			access: {
				actorAccountId: "actor",
				threadCreatorAccountId: "actor",
				canResolveCommentThread: false,
				canReopenCommentThread: false,
			},
			client,
		});
		document.body.replaceChildren(control.element);
		const harness = window as ThreadStatusHarnessWindow;
		harness.__threadStatusControl = control;
		harness.__threadStatusCalls = calls;
	});

	await page.getByTestId("comment-thread-resolve").click();
	await expect(page.getByTestId("comment-thread-status-label")).toHaveText(
		"已解决",
	);
	expect(
		await page.evaluate(
			() =>
				(window as ThreadStatusHarnessWindow).__threadStatusControl
					?.replyAvailability,
		),
	).toEqual({
		allowed: false,
		message: "这条讨论已解决，请先重新打开后再回复。",
	});

	const reopened = await page.evaluate(async () => {
		const control = (window as ThreadStatusHarnessWindow).__threadStatusControl;
		if (!control) throw new Error("thread status control was not initialized");
		const response = await control.reopen();
		return {
			responseStatus: response.status,
			currentStatus: control.status,
			replyAvailability: control.replyAvailability,
		};
	});
	expect(reopened).toEqual({
		responseStatus: "Open",
		currentStatus: "Open",
		replyAvailability: { allowed: true, message: null },
	});
	await expect(page.getByTestId("comment-thread-resolve")).toBeVisible();
	expect(
		await page.evaluate(
			() => (window as ThreadStatusHarnessWindow).__threadStatusCalls,
		),
	).toEqual(["resolve:resource-1:thread-1", "reopen:resource-1:thread-1"]);
});

test("comment thread status control hides actions without creator or capability", async ({
	page,
}) => {
	await page.goto("/login");
	await page.evaluate(async () => {
		const moduleUrl = new URL(
			"/src/components/comment-thread-status.ts",
			window.location.origin,
		).href;
		const { createCommentThreadStatusControl } = await import(moduleUrl);
		const control = createCommentThreadStatusControl({
			resourceId: "resource-1",
			threadId: "thread-1",
			status: "Open",
			access: {
				actorAccountId: "another-user",
				threadCreatorAccountId: "creator",
				canResolveCommentThread: false,
				canReopenCommentThread: false,
			},
			client: {
				async resolveCommentThread() {
					throw new Error("must not be called");
				},
				async reopenCommentThread() {
					throw new Error("must not be called");
				},
			},
		});
		document.body.replaceChildren(control.element);
	});

	await expect(page.getByTestId("comment-thread-resolve")).toHaveCount(0);
	await expect(page.getByTestId("comment-thread-reopen")).toHaveCount(0);
});

test("client SDK uses resource-scoped Resolve and Reopen routes", async () => {
	const globalWindow = globalThis as typeof globalThis & { window?: Window };
	const originalWindow = globalWindow.window;
	const requests: Array<{ url: string; method: string | undefined }> = [];
	const resolveResponse = {
		resourceId: "resource-1",
		threadId: "thread-1",
		status: "Resolved" as const,
		resolvedAt: "2026-09-25T00:00:00Z",
		resolvedBy: "actor",
	};
	const reopenResponse = {
		resourceId: "resource-1",
		threadId: "thread-1",
		status: "Open" as const,
		resolvedAt: null,
		resolvedBy: null,
	};
	Object.defineProperty(globalThis, "window", {
		configurable: true,
		value: {
			fetch: async (url: string, init?: RequestInit) => {
				requests.push({ url, method: init?.method });
				const body = url.endsWith("/resolve")
					? resolveResponse
					: reopenResponse;
				return new Response(JSON.stringify(body), {
					status: 200,
					headers: { "content-type": "application/json" },
				});
			},
		} as unknown as Window,
	});
	try {
		const client = new DomClient({ baseUrl: "/v1", deviceId: "test-device" });
		expect(await client.resolveCommentThread("resource-1", "thread-1")).toEqual(
			resolveResponse,
		);
		expect(await client.reopenCommentThread("resource-1", "thread-1")).toEqual(
			reopenResponse,
		);
		expect(requests).toEqual([
			{
				url: "/v1/resources/resource-1/comments/threads/thread-1/resolve",
				method: "POST",
			},
			{
				url: "/v1/resources/resource-1/comments/threads/thread-1/reopen",
				method: "POST",
			},
		]);
	} finally {
		if (originalWindow === undefined) {
			Reflect.deleteProperty(globalThis, "window");
		} else {
			Object.defineProperty(globalThis, "window", {
				configurable: true,
				value: originalWindow,
			});
		}
	}
});
