/**
 * Browser E2E acceptance suite — the 9 browser-semantic scenarios (plan
 * Task 30). Each test maps 1:1 to a @browser scenario in
 * docs/behavior/features/account-auth-session.feature:
 *
 * 1. Scenario 26  (FR-AUTH-013) multi-tab shared device session
 * 2. Scenario 30  (FR-AUTH-016) realtime disconnect on replacement (close 4001)
 * 3. Scenario 31  (FR-AUTH-017) SessionReplaced dialog visible + distinct copy
 * 4. Scenario 32  (FR-AUTH-017) re-login establishes a brand-new session
 * 5. Scenario 33  (FR-AUTH-019) unsynced draft preserved (not silently discarded)
 * 6. Scenario 34  (FR-AUTH-019) re-login keeps local draft recoverable
 * 7. Scenario 35  (FR-AUTH-019) draft export/backup
 * 8. Scenario 38  (FR-AUTH-021) refresh + browser-restart session recovery
 * 9. Scenario 39  (FR-AUTH-021) replaced session NOT restored after refresh
 *
 * Session semantics used here:
 * - Devices are independent browser contexts (separate cookie jars -> separate
 *   dom_device identities -> separate device slots).
 * - The realtime handshake authenticates against the Valkey session cache,
 *   which is populated by LOGIN (registration's auto-session is not cached),
 *   so "device A" always LOGS IN before opening the editor.
 * - The 2-device quota replaces the OLDEST active session when device C logs
 *   in, so C's login must happen AFTER A's realtime socket is open.
 *
 * Discipline: auto-waiting only (expect(...).toBeVisible({timeout})), no
 * arbitrary sleeps. Each test uses a unique account email so repeated runs on
 * the shared dom_dev database never collide.
 */

import { readFile } from "node:fs/promises";

import {
	type Browser,
	type BrowserContext,
	expect,
	type Page,
	test,
} from "@playwright/test";

const PASSWORD = "Str0ng#Pass123";

let seed = 0;
function freshEmail(label: string): string {
	seed += 1;
	return `e2e-${label}-${Date.now()}-${String(seed).padStart(2, "0")}@example.com`;
}

/** Fill + submit the auth form (register or login page). */
async function submitAuthForm(
	page: Page,
	email: string,
	password: string,
): Promise<void> {
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill(password);
	await page.getByTestId("password-input").press("Enter");
}

/** Register a fresh account through the UI; lands on /workspace. */
async function registerAccount(page: Page, email: string): Promise<void> {
	await page.goto("/register");
	await submitAuthForm(page, email, PASSWORD);
	await expect(page).toHaveURL("/workspace");
	await expect(page.getByTestId("workspace-email")).toHaveText(email);
}

/** Log a browser context into an EXISTING account via the /login page. */
async function loginDevice(page: Page, email: string): Promise<void> {
	await page.goto("/login");
	await submitAuthForm(page, email, PASSWORD);
	await expect(page).toHaveURL("/workspace");
	await expect(page.getByTestId("workspace-email")).toHaveText(email);
}

/**
 * Register the account through the UI in a throwaway context (so no test
 * device keeps the registration auto-session — registration sessions are not
 * cached in Valkey and would pollute the cookie jar), then log device A and
 * device B in via /login. Device C's login is deliberately NOT performed here
 * — the replacement must fire while A's realtime socket is already open.
 *
 * Session math (2-device quota, oldest-by-createdAt eviction):
 *  t0 registration (device R) -> evicted when B logs in
 *  t1 A login, t2 B login, t3 C login -> C's login replaces A (oldest).
 */
async function setupAB(
	browser: Browser,
	ctxA: BrowserContext,
	ctxB: BrowserContext,
	email: string,
): Promise<[Page, Page]> {
	const seed = await browser.newContext();
	try {
		const seedPage = await seed.newPage();
		await registerAccount(seedPage, email);
	} finally {
		await seed.close();
	}

	const pageA = await ctxA.newPage();
	await loginDevice(pageA, email);
	const pageB = await ctxB.newPage();
	await loginDevice(pageB, email);
	return [pageA, pageB];
}

/** Login device C — the third device login that replaces A (oldest). */
async function loginDeviceC(
	ctxC: BrowserContext,
	email: string,
): Promise<Page> {
	const pageC = await ctxC.newPage();
	await loginDevice(pageC, email);
	return pageC;
}

/** Current session id as reported by /v1/auth/session from a page cookie jar. */
function currentSessionId(page: Page): Promise<string> {
	return page.evaluate(async () => {
		const response = await fetch("/v1/auth/session", {
			credentials: "same-origin",
		});
		if (!response.ok) {
			return "";
		}
		const body = (await response.json()) as { sessionId?: string };
		return body.sessionId ?? "";
	});
}

/** Open the collaborative editor and wait until the realtime socket is live. */
async function openEditor(page: Page): Promise<void> {
	await page.goto("/editor");
	await expect(page.getByTestId("realtime-status")).toHaveText("connected", {
		timeout: 5_000,
	});
}

// ---------------------------------------------------------------------------
// Scenario 26 — FR-AUTH-013: multi-tab shares one device session
// ---------------------------------------------------------------------------

test("Scenario 26: two tabs in one browser share the same device session", async ({
	context,
}) => {
	const email = freshEmail("mtab");
	const tab1 = await context.newPage();
	await registerAccount(tab1, email);

	// Second tab of the SAME browser context: automatic session reuse, no
	// second login, no extra device slot.
	const tab2 = await context.newPage();
	await tab2.goto("/workspace");
	await expect(tab2).toHaveURL("/workspace");
	await expect(tab2.getByTestId("workspace-email")).toHaveText(email);

	// Both tabs share the SAME session id -> exactly one active device session.
	const session1 = await currentSessionId(tab1);
	const session2 = await currentSessionId(tab2);
	expect(session1).not.toBe("");
	expect(session2).toBe(session1);
});

// ---------------------------------------------------------------------------
// Scenario 30 — FR-AUTH-016: realtime disconnect on replacement
// ---------------------------------------------------------------------------

test("Scenario 30: replaced device realtime socket closes with 4001", async ({
	browser,
}) => {
	const email = freshEmail("rt");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		// Device A opens the collaborative editor -> live realtime connection.
		await openEditor(pageA);

		// Device C login replaces the OLDEST active session (device A).
		const pageC = await loginDeviceC(ctxC, email);
		expect(pageC).not.toBeNull();

		// A's realtime socket is force-closed by the server with code 4001 and
		// the replacement dialog appears; A loses API authority.
		await expect(pageA.getByTestId("realtime-status")).toHaveText(
			"closed:4001",
			{
				timeout: 5_000,
			},
		);
		await expect(pageA.getByTestId("session-replaced-dialog")).toBeVisible();
		expect(await currentSessionId(pageA)).toBe("");
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 31 — FR-AUTH-017: SessionReplaced dialog + re-login entry
// ---------------------------------------------------------------------------

test("Scenario 31: old device shows the SessionReplaced dialog with re-login", async ({
	browser,
}) => {
	const email = freshEmail("dlg");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		await openEditor(pageA);
		await loginDeviceC(ctxC, email);

		const dialog = pageA.getByTestId("session-replaced-dialog");
		await expect(dialog).toBeVisible({ timeout: 5_000 });
		// Distinct user-visible copy (BDD FR-AUTH-017) — not a network error.
		await expect(dialog).toContainText(
			"当前账号已在另一台设备登录，本设备已下线",
		);
		await expect(pageA.getByTestId("session-replaced-relogin")).toBeVisible();
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 32 — FR-AUTH-017: re-login on the replaced device
// ---------------------------------------------------------------------------

test("Scenario 32: re-login on the replaced device establishes a new session", async ({
	browser,
}) => {
	const email = freshEmail("relogin");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		await openEditor(pageA);
		await loginDeviceC(ctxC, email);
		await expect(pageA.getByTestId("session-replaced-dialog")).toBeVisible({
			timeout: 5_000,
		});

		// Re-login from the dialog entry -> a NEW, distinct session on device A.
		await pageA.getByTestId("session-replaced-relogin").click();
		await expect(pageA).toHaveURL("/login");
		await loginDevice(pageA, email);
		expect(await currentSessionId(pageA)).not.toBe("");

		// Device A can reconnect realtime with its fresh session.
		await openEditor(pageA);
		await expect(pageA.getByTestId("realtime-status")).toHaveText("connected", {
			timeout: 5_000,
		});
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 33 — FR-AUTH-019: unsynced draft not silently discarded
// ---------------------------------------------------------------------------

test("Scenario 33: unsynced draft survives a session replacement", async ({
	browser,
}) => {
	const email = freshEmail("draft");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		await openEditor(pageA);
		const draftText = `未同步草稿 ${email}`;
		await pageA.getByTestId("editor-draft-textarea").fill(draftText);

		// Device C replacement while the draft is unsynced.
		await loginDeviceC(ctxC, email);

		// Draft is preserved and surfaced — never silently discarded.
		await expect(pageA.getByTestId("session-replaced-dialog")).toBeVisible({
			timeout: 5_000,
		});
		await expect(pageA.getByTestId("draft-recovery-banner")).toBeVisible();
		await expect(pageA.getByTestId("draft-recovery-content")).toHaveText(
			draftText,
		);
		const stored = await pageA.evaluate(() =>
			window.localStorage.getItem("draft_unsaved"),
		);
		expect(stored).toBe(draftText);
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 34 — FR-AUTH-019: re-login keeps the local draft recoverable
// ---------------------------------------------------------------------------

test("Scenario 34: re-login preserves the unsynced draft for recovery", async ({
	browser,
}) => {
	const email = freshEmail("merge");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		await openEditor(pageA);
		const draftText = `草稿在替换后依然可恢复 ${email}`;
		await pageA.getByTestId("editor-draft-textarea").fill(draftText);
		await loginDeviceC(ctxC, email);
		await expect(pageA.getByTestId("session-replaced-dialog")).toBeVisible({
			timeout: 5_000,
		});

		// Re-login on device A; the local draft is NOT silently discarded and
		// stays recoverable/exportable in the editor.
		await pageA.getByTestId("session-replaced-relogin").click();
		await loginDevice(pageA, email);
		await pageA.goto("/editor");
		await expect(pageA.getByTestId("editor-draft-textarea")).toHaveValue(
			draftText,
		);
		const stored = await pageA.evaluate(() =>
			window.localStorage.getItem("draft_unsaved"),
		);
		expect(stored).toBe(draftText);
		await expect(pageA.getByTestId("draft-export-button")).toBeVisible();
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 35 — FR-AUTH-019: draft export / backup
// ---------------------------------------------------------------------------

test("Scenario 35: unsynced draft can be exported as a local backup", async ({
	browser,
}) => {
	const email = freshEmail("export");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		await openEditor(pageA);
		const draftText = `可导出的未同步草稿 ${email}`;
		await pageA.getByTestId("editor-draft-textarea").fill(draftText);
		await loginDeviceC(ctxC, email);
		await expect(pageA.getByTestId("draft-recovery-banner")).toBeVisible({
			timeout: 5_000,
		});

		// Export => a real text-file download containing the draft content.
		const downloadPromise = pageA.waitForEvent("download");
		await pageA.getByTestId("draft-export-button").click();
		const download = await downloadPromise;
		expect(download.suggestedFilename()).toBe("dom-draft.txt");
		const path = await download.path();
		expect(path).not.toBeNull();
		expect(await readFile(path as string, "utf-8")).toBe(draftText);
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 38 — FR-AUTH-021: refresh + browser-restart session recovery
// ---------------------------------------------------------------------------

test("Scenario 38: session survives page refresh and browser restart", async ({
	browser,
}) => {
	const email = freshEmail("refresh");
	const ctx = await browser.newContext();
	try {
		const page = await ctx.newPage();
		await registerAccount(page, email);

		// Page refresh -> cookie-based recovery, no re-login.
		await page.reload();
		await expect(page).toHaveURL("/workspace");
		await expect(page.getByTestId("workspace-email")).toHaveText(email);

		// Browser restart: a NEW context seeded with the persisted cookies
		// (storageState) auto-recovers the session (FR-AUTH-021 AC-021.1).
		const state = await ctx.storageState();
		const restarted = await browser.newContext({ storageState: state });
		try {
			const page2 = await restarted.newPage();
			await page2.goto("/workspace");
			await expect(page2).toHaveURL("/workspace");
			await expect(page2.getByTestId("workspace-email")).toHaveText(email);
			expect(await currentSessionId(page2)).not.toBe("");
		} finally {
			await restarted.close();
		}
	} finally {
		await ctx.close();
	}
});

// ---------------------------------------------------------------------------
// Scenario 39 — FR-AUTH-021: replaced session NOT restored after refresh
// ---------------------------------------------------------------------------

test("Scenario 39: replaced session refresh does not restore login", async ({
	browser,
}) => {
	const email = freshEmail("norestore");
	const ctxA = await browser.newContext();
	const ctxB = await browser.newContext();
	const ctxC = await browser.newContext();
	try {
		const [pageA] = await setupAB(browser, ctxA, ctxB, email);
		await openEditor(pageA);
		await loginDeviceC(ctxC, email);
		await expect(pageA.getByTestId("session-replaced-dialog")).toBeVisible({
			timeout: 5_000,
		});

		// Refresh on the replaced device: the "Replaced" session must NOT be
		// resumed — the page falls back to the login entry.
		await pageA.reload();
		await expect(pageA).toHaveURL("/login");
		expect(await currentSessionId(pageA)).toBe("");
	} finally {
		await ctxA.close();
		await ctxB.close();
		await ctxC.close();
	}
});
