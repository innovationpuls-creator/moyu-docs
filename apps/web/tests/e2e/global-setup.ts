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
	const probe = spawnSync(
		"docker",
		["exec", "dom-rt-e2e", "nats", "server", "check", "connection"],
		{ encoding: "utf8" },
	);
	if (probe.status === 0) return;
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
