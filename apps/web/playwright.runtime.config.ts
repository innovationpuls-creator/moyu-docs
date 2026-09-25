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
	testMatch: [
		"resource-runtime.spec.ts",
		"editor-core-asset-insertion.spec.ts",
		"asset-upload-idempotency.spec.ts",
	],
	fullyParallel: false,
	workers: 1,
	timeout: 30_000,
	expect: { timeout: 10_000 },
	retries: 0,
	reporter: [["list"]],
	use: {
		baseURL: "http://localhost:5174",
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
			name: "chromium-resource-runtime",
			use: { ...devices["Desktop Chrome"] },
		},
	],
	webServer: {
		command:
			"pnpm --filter @dom/web exec vite --host localhost --port 5174 --strictPort",
		url: "http://localhost:5174",
		cwd: resolve(appRoot, "..", ".."),
		reuseExistingServer: true,
		timeout: 60_000,
	},
});
