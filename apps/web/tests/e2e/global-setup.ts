/** Verify the externally managed NATS service before the browser suite starts. */
import { spawnSync } from "node:child_process";

export default function globalSetup(): void {
	const tcpProbe = spawnSync(
		process.execPath,
		[
			"-e",
			"require('net').connect(4222,'127.0.0.1',()=>process.exit(0))" +
				".on('error',()=>process.exit(1)).setTimeout(2000,()=>process.exit(1))",
		],
		{ encoding: "utf8" },
	);
	if (tcpProbe.status !== 0) {
		throw new Error(
			"NATS must be available at 127.0.0.1:4222 before the browser suite runs.",
		);
	}
}
