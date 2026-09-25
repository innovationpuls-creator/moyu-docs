import { expect, test } from "@playwright/test";

const browserEntry = "/tests/fixtures/resource-runtime-browser-entry.ts";

test("resource snapshots survive offline reloads and remain account scoped", async ({
	browser,
}) => {
	const context = await browser.newContext();
	const firstTab = await context.newPage();
	const secondTab = await context.newPage();
	try {
		await firstTab.goto("/");
		await firstTab.evaluate(async (entry) => import(entry), browserEntry);
		await secondTab.goto("/");
		await secondTab.evaluate(async (entry) => import(entry), browserEntry);
		await firstTab.evaluate(
			() =>
				new Promise<void>((resolve, reject) => {
					const request = indexedDB.deleteDatabase("dom-resource-runtime");
					request.onsuccess = () => resolve();
					request.onerror = () => reject(request.error);
					request.onblocked = () =>
						reject(new Error("Database delete blocked"));
				}),
		);

		const initialSource = await firstTab.evaluate(async () => {
			const runtime = window.createResourceRuntimeForBrowserTest(
				"replica-first-tab",
				true,
			);
			const opened = await runtime.openResource("account-a", "resource-a");
			await runtime.persistLocalState(
				"account-a",
				"resource-a",
				new Uint8Array([1, 2, 3]),
				opened.resource,
			);
			runtime.dispose();
			return opened.source;
		});
		expect(initialSource).toBe("server");

		const broadcastEvent = firstTab.evaluate(async () => {
			const runtime = window.createResourceRuntimeForBrowserTest(
				"observer-tab",
				false,
			);
			return new Promise<{ replicaId: string; revision: number }>((resolve) => {
				let unsubscribe = () => {};
				const timeout = window.setTimeout(() => {
					unsubscribe();
					runtime.dispose();
					resolve({ replicaId: "timeout", revision: 0 });
				}, 5000);
				unsubscribe = runtime.subscribeLocalUpdates(
					"account-a",
					"resource-a",
					(event) => {
						window.clearTimeout(timeout);
						unsubscribe();
						runtime.dispose();
						resolve({
							replicaId: event.replicaId,
							revision: event.revision,
						});
					},
				);
			});
		});

		await context.setOffline(true);
		const secondTabResult = await secondTab.evaluate(async () => {
			const runtime = window.createResourceRuntimeForBrowserTest(
				"replica-second-tab",
				false,
			);
			const opened = await runtime.openResource("account-a", "resource-a");
			await runtime.persistLocalState(
				"account-a",
				"resource-a",
				new Uint8Array([4, 5, 6]),
				opened.resource,
			);
			runtime.dispose();
			return {
				source: opened.source,
				snapshotCount: opened.localSnapshots.length,
			};
		});
		expect(secondTabResult).toEqual({
			source: "offline-cache",
			snapshotCount: 1,
		});
		expect(await broadcastEvent).toEqual({
			replicaId: "replica-second-tab",
			revision: 1,
		});

		const restored = await firstTab.evaluate(async () => {
			const runtime = window.createResourceRuntimeForBrowserTest(
				"replica-reader",
				false,
			);
			const opened = await runtime.openResource("account-a", "resource-a");
			const confirmed = await runtime.recordConfirmedRevisions(
				"account-a",
				"resource-a",
				"replica-second-tab",
				{ acceptedRevision: 1, durableRevision: 1 },
			);
			const olderReceipt = await runtime.recordConfirmedRevisions(
				"account-a",
				"resource-a",
				"replica-second-tab",
				{ acceptedRevision: 0, durableRevision: 0 },
			);
			let futureReceiptRejected = false;
			try {
				await runtime.recordConfirmedRevisions(
					"account-a",
					"resource-a",
					"replica-second-tab",
					{ acceptedRevision: 2 },
				);
			} catch {
				futureReceiptRejected = true;
			}
			let accountIsolation = false;
			let resourceIsolation = false;
			try {
				await runtime.openResource("account-b", "resource-a");
			} catch {
				accountIsolation = true;
			}
			try {
				await runtime.openResource("account-a", "resource-b");
			} catch {
				resourceIsolation = true;
			}
			let clearRequiresConfirmation = false;
			try {
				await runtime.clearLocalResource(
					"account-a",
					"resource-a",
					{} as never,
				);
			} catch {
				clearRequiresConfirmation = true;
			}
			await runtime.clearLocalResource("account-a", "resource-a", {
				confirmDiscardUnsyncedChanges: true,
			});
			runtime.dispose();
			return {
				source: opened.source,
				snapshotCount: opened.localSnapshots.length,
				localUpdateIsAmbiguous: opened.localUpdate === null,
				confirmedRevision: confirmed.revision,
				acceptedRevision: confirmed.acceptedRevision,
				durableRevision: confirmed.durableRevision,
				olderReceiptDidNotRegress:
					olderReceipt.acceptedRevision === confirmed.acceptedRevision &&
					olderReceipt.durableRevision === confirmed.durableRevision,
				futureReceiptRejected,
				accountIsolation,
				resourceIsolation,
				clearRequiresConfirmation,
			};
		});
		expect(restored).toEqual({
			source: "offline-cache",
			snapshotCount: 2,
			localUpdateIsAmbiguous: true,
			confirmedRevision: 1,
			acceptedRevision: 1,
			durableRevision: 1,
			olderReceiptDidNotRegress: true,
			futureReceiptRejected: true,
			accountIsolation: true,
			resourceIsolation: true,
			clearRequiresConfirmation: true,
		});
	} finally {
		await context.close();
	}
});
