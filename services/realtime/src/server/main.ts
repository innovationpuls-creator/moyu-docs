/**
 * Realtime gateway dev entry (plan Task 30).
 *
 * Starts the WebSocket gateway on ``REALTIME_PORT`` (default 8765) so Playwright
 * webServer can launch it alongside the API and the web dev server, and
 * registers a tiny plain-HTTP ``/healthz`` handler (the gateway's server is
 * otherwise upgrade-only, which would leave Playwright's URL readiness probe
 * unanswered).
 */

import { startRealtimeServer } from "./websocket_server.js";

const PORT = Number(process.env.REALTIME_PORT ?? 8765);
const VALKEY_URL = process.env.VALKEY_URL ?? "redis://localhost:6379/14";

const handle = startRealtimeServer({ port: PORT, valkeyUrl: VALKEY_URL });

handle.server.on("request", (_request, response) => {
	response.writeHead(200, { "content-type": "text/plain" });
	response.end("ok");
});

handle.ready
	.then(() => {
		console.log(`[dom/realtime] listening on ws://localhost:${PORT}`);
	})
	.catch((error: unknown) => {
		console.error("[dom/realtime] failed to start:", error);
		process.exitCode = 1;
	});

const shutdown = async (): Promise<void> => {
	await handle.close();
	process.exit(0);
};
process.on("SIGINT", () => {
	void shutdown();
});
process.on("SIGTERM", () => {
	void shutdown();
});
