import { expect, test } from "@playwright/test";

test("offline navigation uses only the versioned app shell cache", async ({
	browser,
}) => {
	const context = await browser.newContext();
	const page = await context.newPage();
	try {
		await page.goto("/");
		await page.evaluate(() => navigator.serviceWorker.ready);
		await expect
			.poll(() =>
				page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
			)
			.toBe(true);

		const cachedShell = await page.evaluate(async () => {
			const names = await caches.keys();
			const appCaches = names.filter((name) =>
				name.startsWith("dom-app-shell-"),
			);
			const urls = (
				await Promise.all(
					appCaches.map(async (name) => {
						const cache = await caches.open(name);
						return (await cache.keys()).map(
							(request) => new URL(request.url).pathname,
						);
					}),
				)
			).flat();
			return { appCaches, urls };
		});
		expect(cachedShell.appCaches).toHaveLength(1);
		expect(cachedShell.urls).toContain("/index.html");
		expect(
			cachedShell.urls.some((path) =>
				/^\/assets\/[^/]*(?:[-.])[A-Za-z0-9_-]{8,}\.js$/.test(path),
			),
		).toBe(true);
		expect(
			cachedShell.urls.every(
				(path) =>
					path === "/index.html" ||
					/^\/assets\/[^/]*(?:[-.])[A-Za-z0-9_-]{8,}\.(?:js|css)$/.test(path),
			),
		).toBe(true);

		await context.setOffline(true);
		await page.goto("/editor?resourceId=offline-shell-probe", {
			waitUntil: "domcontentloaded",
		});
		const navigatorReportsOnline = await page.evaluate(() => navigator.onLine);
		await expect(page.getByTestId("app-offline-status")).toHaveText(
			navigatorReportsOnline ? "网络状态：无法连接服务" : "网络状态：离线",
		);
		expect(page.url()).toContain("/editor?resourceId=offline-shell-probe");
	} finally {
		await context.close();
	}
});
