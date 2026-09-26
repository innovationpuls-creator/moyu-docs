/**
 * Playwright config for the DOM web E2E suite (plan Task 30).
 *
 * Four web servers are started for the browser suite:
 *  1. the FastAPI auth service (uvicorn, port 8000) — the /v1 API;
 *  2. the realtime WebSocket gateway (@dom/realtime, port 8765);
 *  3. the web dev server (vite, port 5173) which proxies /v1 -> the API.
 *  4. the production preview (port 4173) for Service Worker offline flows.
 *
 * Chromium only (the browser-semantics scenarios are auth/session flows that
 * do not depend on engine-specific behavior; firefox/webkit are optional —
 * see the task report). PLAYWRIGHT_BROWSERS_PATH is forced to a
 * workspace-local directory because user-level caches are not writable in
 * this environment.
 */

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const globalSetup = "./tests/e2e/global-setup.ts";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");

// Workspace-local browser installation (user caches unwritable).
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(
	repoRoot,
	".playwright-browsers",
);

const apiEnv = {
	DATABASE_URL: "postgresql+psycopg://torch@localhost:5432/dom_dev",
	VALKEY_URL: "redis://localhost:6379/14",
	UV_CACHE_DIR: resolve(repoRoot, ".uv-cache"),
};

export default defineConfig({
	globalSetup,
	testDir: "./tests/e2e",
	fullyParallel: false,
	workers: 1,
	timeout: 30_000,
	expect: { timeout: 10_000 },
	retries: 0,
	reporter: [["list"]],
	use: {
		baseURL: "http://localhost:5173",
		trace: "retain-on-failure",
	},
	projects: [
		{
			name: "chromium",
			testIgnore: "**/offline_reconnect.spec.ts",
			use: {
				...devices["Desktop Chrome"],
				// Each test creates its own browser contexts; cookies are always
				// per-context (fresh device identity per context).
				permissions: [],
			},
		},
		{
			name: "chromium-offline-reconnect",
			testMatch: "**/offline_reconnect.spec.ts",
			use: {
				...devices["Desktop Chrome"],
				baseURL: "http://localhost:4173",
				permissions: [],
			},
		},
	],
	webServer: [
		{
			command:
				"uv run --directory services/api uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000",
			url: "http://127.0.0.1:8000/healthz",
			cwd: repoRoot,
			env: { ...apiEnv },
			reuseExistingServer: true,
			timeout: 60_000,
		},
		{
			command:
				"pnpm --filter @dom/web build && pnpm --filter @dom/web exec vite preview --config vite.e2e-preview.config.ts --host localhost --port 4173 --strictPort",
			url: "http://localhost:4173",
			cwd: repoRoot,
			reuseExistingServer: true,
			timeout: 120_000,
		},
		{
			command: "pnpm --filter @dom/realtime dev",
			url: "http://127.0.0.1:8765/healthz",
			cwd: repoRoot,
			env: {
				VALKEY_URL: "redis://localhost:6379/14",
				REALTIME_PORT: "8765",
				REALTIME_DATABASE_URL: "postgresql://torch@localhost:5432/dom_dev",
			},
			reuseExistingServer: true,
			timeout: 60_000,
		},
		{
			command: "pnpm --filter @dom/web exec vite --port 5173 --strictPort",
			url: "http://localhost:5173/",
			cwd: repoRoot,
			reuseExistingServer: true,
			timeout: 60_000,
		},
	],
});
