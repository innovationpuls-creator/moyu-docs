/**
 * Global setup: provision the NATS test container BEFORE Playwright boots the
 * webServer stack (the realtime gateway connects its relay at startup).
 * Best-effort: a pre-existing healthy container is reused.
 */
import { spawnSync } from "node:child_process";

export default function globalSetup(): void {
	// NOTE: the realtime gateway is provisioned OUTSIDE the suite (see
	// ledger): the harness's own "pnpm --filter @dom/realtime dev" boot is
	// environmentally flaky (silently dies post-healthcheck), so the suite
	// reuses the externally-started gateway on :8765.
	//
	// Probe = host-side TCP connect to the NATS client port (4222). The
	// nats:2.10-alpine image ships no `nats` CLI, so a container-internal
	// `nats server check connection` probe ALWAYS fails and forced an
	// rm+recreate of a healthy container on every suite run, which severed
	// the API/gateway NATS connections they reuse (journal publish then
	// 500s with ConnectionClosedError). Reachability of 4222 is the signal
	// that actually matters here.
	const tcpProbe = spawnSync(
		process.execPath,
		[
			"-e",
			"require('net').connect(4222,'127.0.0.1',()=>process.exit(0))" +
				".on('error',()=>process.exit(1)).setTimeout(2000,()=>process.exit(1))",
		],
		{ encoding: "utf8" },
	);
	if (tcpProbe.status === 0) return;
	spawnSync("docker", ["rm", "-f", "dom-rt-e2e"], { encoding: "utf8" });
	const run = spawnSync(
		"docker",
		[
			"run",
			"-d",
			"--name",
			"dom-rt-e2e",
			"-p",
			"4222:4222",
			"nats:2.10-alpine",
			"-js",
		],
		{ encoding: "utf8" },
	);
	if (run.status !== 0) {
		throw new Error(`NATS provisioning failed: ${run.stderr}`);
	}
}
