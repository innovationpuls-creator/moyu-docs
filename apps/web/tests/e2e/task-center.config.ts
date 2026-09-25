import { resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";

const appRoot = resolve(import.meta.dirname, "..", "..");
const repoRoot = resolve(appRoot, "..", "..");
process.env.PLAYWRIGHT_BROWSERS_PATH ??= resolve(
	repoRoot,
	".playwright-browsers",
);

export default defineConfig({
	testDir: import.meta.dirname,
	testMatch: "task-center.spec.ts",
	fullyParallel: false,
	workers: 1,
	timeout: 30_000,
	expect: { timeout: 10_000 },
	retries: 0,
	reporter: [["list"]],
	use: {
		baseURL: "http://localhost:5187",
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
			name: "chromium-task-center",
			use: { ...devices["Desktop Chrome"] },
		},
	],
	webServer: {
		command:
			"pnpm --filter @dom/web exec vite --host localhost --port 5187 --strictPort",
		url: "http://localhost:5187",
		cwd: repoRoot,
		reuseExistingServer: false,
		timeout: 60_000,
	},
});
