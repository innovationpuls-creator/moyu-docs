/**
 * Task 25: WebSocket handshake session authentication (plan Task 25 §3-§5).
 *
 * Integration tests against the REAL local Valkey service (db 15,
 * FLUSHDB per test) — no mocks for the cache path.
 *
 * - a handshake with a valid seeded ``dom_session`` cookie opens the socket;
 * - a missing / unknown / corrupt / expired / replaced session is rejected
 *   with an HTTP 401 upgrade response (ws client sees 'unexpected-response').
 */

import { once } from "node:events";
import type { AddressInfo } from "node:net";

import { Redis } from "ioredis";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import WebSocket from "ws";

import type { SessionCachedData } from "../src/auth/session_authenticator.js";
import {
	type RealtimeServerHandle,
	SESSION_COOKIE_NAME,
	startRealtimeServer,
} from "../src/server/websocket_server.js";

const VALKEY_URL = "redis://localhost:6379/15";
const HOUR_MS = 60 * 60 * 1000;

function utcIso(offsetMs: number): string {
	return new Date(Date.now() + offsetMs).toISOString();
}

interface SessionSeed {
	seed: SessionCachedData;
	/** raw JSON stored at session:{id} — defaults to JSON.stringify(seed) */
	raw?: string;
}

function activeSession(sessionId: string): SessionSeed {
	return {
		seed: {
			session_id: sessionId,
			account_id: "00000000-0000-0000-0000-00000000000a",
			device_id: "device-1",
			status: "Active",
			expires_at: utcIso(HOUR_MS),
			last_strong_auth_at: utcIso(-60_000),
		},
	};
}

async function seed(valkey: Redis, seedSet: SessionSeed): Promise<void> {
	await valkey.set(
		`session:${seedSet.seed.session_id}`,
		seedSet.raw ?? JSON.stringify(seedSet.seed),
	);
}

function httpPort(server: RealtimeServerHandle["server"]): number {
	const address = server.address() as AddressInfo;
	return address.port;
}

type ConnectResult =
	| { outcome: "open" }
	| { outcome: "rejected"; statusCode: number };

/** Open a WS handshake and resolve with 'open' or the upgrade-rejection 401. */
function connectOnce(
	url: string,
	cookie: string | null,
	timeoutMs = 3_000,
): Promise<ConnectResult> {
	return new Promise((resolve, reject) => {
		const options =
			cookie === null
				? undefined
				: { headers: { Cookie: `${SESSION_COOKIE_NAME}=${cookie}` } };
		const ws = new WebSocket(url, options);
		const timer = setTimeout(() => {
			ws.terminate();
			reject(
				new Error(`timed out after ${timeoutMs}ms waiting for the WS outcome`),
			);
		}, timeoutMs);
		ws.on("open", () => {
			clearTimeout(timer);
			ws.close();
			resolve({ outcome: "open" });
		});
		ws.on("unexpected-response", (_request, response) => {
			clearTimeout(timer);
			response.resume();
			ws.terminate();
			resolve({ outcome: "rejected", statusCode: response.statusCode ?? 0 });
		});
		// 'unexpected-response' is always accompanied by an 'error' event;
		// without a listener the error would be thrown as unhandled.
		ws.on("error", () => {});
	});
}

describe("websocket session authentication (real valkey db 15)", () => {
	let valkey: Redis;
	let handle: RealtimeServerHandle;
	let baseUrl: string;

	beforeEach(async () => {
		valkey = new Redis(VALKEY_URL);
		await valkey.flushdb();
		handle = startRealtimeServer({ port: 0, valkeyUrl: VALKEY_URL });
		await once(handle.server, "listening");
		baseUrl = `ws://127.0.0.1:${httpPort(handle.server)}`;
	});

	afterEach(async () => {
		await handle.close();
		valkey.disconnect();
	});

	it("opens a connection for a valid Active session cookie", async () => {
		const sessionId = "00000000-0000-0000-0000-0000000000c1";
		await seed(valkey, activeSession(sessionId));

		const result = await connectOnce(baseUrl, sessionId);

		expect(result).toEqual({ outcome: "open" });
	});

	it("rejects the handshake with 401 when the session cookie is missing", async () => {
		const result = await connectOnce(baseUrl, null);

		expect(result.outcome).toBe("rejected");
		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});

	it("rejects with 401 for an unknown session id", async () => {
		const result = await connectOnce(
			baseUrl,
			"00000000-0000-0000-0000-0000000000c2",
		);

		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});

	it("rejects a cached session without a trusted account identity", async () => {
		const sessionId = "00000000-0000-0000-0000-0000000000c7";
		const seeded = activeSession(sessionId);
		await seed(valkey, {
			...seeded,
			seed: { ...seeded.seed, account_id: "" },
		});

		const result = await connectOnce(baseUrl, sessionId);

		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});

	it("rejects with 401 when the cached payload is corrupt (not JSON)", async () => {
		const sessionId = "00000000-0000-0000-0000-0000000000c3";
		await valkey.set(`session:${sessionId}`, "not-json{{");

		const result = await connectOnce(baseUrl, sessionId);

		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});

	it("rejects with 401 for a Replaced session", async () => {
		const sessionId = "00000000-0000-0000-0000-0000000000c4";
		const seeded = activeSession(sessionId);
		await seed(valkey, {
			...seeded,
			seed: { ...seeded.seed, status: "Replaced" },
		});

		const result = await connectOnce(baseUrl, sessionId);

		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});

	it("rejects with 401 for an Expired session", async () => {
		const sessionId = "00000000-0000-0000-0000-0000000000c5";
		const seeded = activeSession(sessionId);
		await seed(valkey, {
			...seeded,
			seed: { ...seeded.seed, status: "Expired" },
		});

		const result = await connectOnce(baseUrl, sessionId);

		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});

	it("rejects with 401 when expires_at is in the past", async () => {
		const sessionId = "00000000-0000-0000-0000-0000000000c6";
		const seeded = activeSession(sessionId);
		await seed(valkey, {
			...seeded,
			seed: { ...seeded.seed, expires_at: utcIso(-10_000) },
		});

		const result = await connectOnce(baseUrl, sessionId);

		expect(result).toMatchObject({ outcome: "rejected", statusCode: 401 });
	});
});
