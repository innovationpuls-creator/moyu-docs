import { resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";

const appRoot = resolve(import.meta.dirname);
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(
	appRoot,
	"..",
	"..",
	".playwright-browsers",
);

export default defineConfig({
	testDir: "./tests/offline",
	testMatch: "offline-shell.spec.ts",
	fullyParallel: false,
	workers: 1,
	timeout: 60_000,
	expect: { timeout: 15_000 },
	retries: 0,
	reporter: [["list"]],
	use: {
		baseURL: "http://localhost:4173",
		trace: "retain-on-failure",
		...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
			? {
					launchOptions: {
						executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
					},
				}
			: {}),
	},
	projects: [
		{
			name: "chromium-offline-shell",
			use: { ...devices["Desktop Chrome"] },
		},
	],
	webServer: {
		command:
			"pnpm --filter @dom/web build && pnpm --filter @dom/web exec vite preview --host localhost --port 4173 --strictPort",
		url: "http://localhost:4173",
		cwd: resolve(appRoot, "..", ".."),
		reuseExistingServer: true,
		timeout: 120_000,
	},
});
