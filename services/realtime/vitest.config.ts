import { defineConfig } from "vitest/config";

export default defineConfig({
	test: {
		environment: "node",
		// The test suites share ONE real Valkey database (localhost db 15, per
		// plan Task 25/26): run the files sequentially so FLUSHDB per test can
		// never race a peer file's keys or pubsub assertions.
		fileParallelism: false,
		testTimeout: 10_000,
		hookTimeout: 10_000,
	},
});
