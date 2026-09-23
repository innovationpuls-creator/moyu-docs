/**
 * Task 26: SessionReplaced invalidation dispatch (plan Task 26 §1-§2).
 *
 * The SessionInvalidator registers live connections by sessionId and consumes
 * the shared Valkey pubsub channel ``events:session_invalidated`` — the SAME
 * channel the API layer publishes to on login replacement (FR-AUTH-016/017,
 * doc 16 §80-§82). Firing the event through a REAL valkey PUBLISH keeps the
 * integration honest; only the socket itself is a harness stub (the seam is a
 * structural WebSocket with vi.fn() send/close).
 *
 * A server-level end-to-end case (real ws client + real publish) proves the
 * full wiring: frame received, then close code 4001.
 */

import { once } from "node:events";
import type { AddressInfo } from "node:net";

import { Redis } from "ioredis";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebSocket } from "ws";

import {
	SESSION_INVALIDATION_CHANNEL,
	SESSION_REPLACED_CLOSE_CODE,
	SessionInvalidator,
	type SessionReplacedFrame,
} from "../src/connection/session_invalidator.js";
import {
	type RealtimeServerHandle,
	SESSION_COOKIE_NAME,
	startRealtimeServer,
} from "../src/server/websocket_server.js";

const VALKEY_URL = "redis://localhost:6379/15";
const TEST_SESSION_ID = "00000000-0000-0000-0000-0000000000e1";

async function waitFor(
	predicate: () => boolean,
	timeoutMs = 3_000,
): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	while (!predicate()) {
		if (Date.now() > deadline)
			throw new Error("condition not met before timeout");
		await new Promise((resolve) => setTimeout(resolve, 10));
	}
}

/** Harness stub satisfying the invalidator's structural socket interface:
 * vi.fn() send/close with a chosen readyState. */
function mockSocket(readyState: number) {
	return {
		readyState,
		send: vi.fn(),
		close: vi.fn(),
	};
}

describe("session invalidator (real valkey pubsub db 15)", () => {
	let valkey: Redis;
	let invalidator: SessionInvalidator;

	beforeEach(async () => {
		valkey = new Redis(VALKEY_URL);
		await valkey.flushdb();
		invalidator = new SessionInvalidator(valkey);
		await invalidator.start();
	});

	afterEach(async () => {
		await invalidator.close();
		valkey.disconnect();
	});

	it("sends the SessionReplaced frame and closes with 4001 on a matching invalidation", async () => {
		const socket = mockSocket(WebSocket.OPEN);
		invalidator.register(TEST_SESSION_ID, socket);

		await valkey.publish(
			SESSION_INVALIDATION_CHANNEL,
			JSON.stringify({ session_id: TEST_SESSION_ID, reason: "NewDeviceLogin" }),
		);
		await waitFor(() => socket.send.mock.calls.length > 0);

		expect(socket.send).toHaveBeenCalledTimes(1);
		const frame = JSON.parse(
			String(socket.send.mock.calls[0][0]),
		) as SessionReplacedFrame;
		expect(frame).toEqual({
			type: "SessionReplaced",
			reason: "NewDeviceLogin",
			message: "当前账号已在另一台设备登录",
		});
		expect(socket.close).toHaveBeenCalledWith(SESSION_REPLACED_CLOSE_CODE);
	});

	it("ignores invalidations for sessions it does not hold", async () => {
		const socket = mockSocket(WebSocket.OPEN);
		invalidator.register(TEST_SESSION_ID, socket);

		await valkey.publish(
			SESSION_INVALIDATION_CHANNEL,
			JSON.stringify({
				session_id: "00000000-0000-0000-0000-0000000000e2",
				reason: "NewDeviceLogin",
			}),
		);
		await new Promise((resolve) => setTimeout(resolve, 150));

		expect(socket.send).not.toHaveBeenCalled();
		expect(socket.close).not.toHaveBeenCalled();
	});

	it("unregisters a closed socket so later events do not touch it", async () => {
		const socket = mockSocket(WebSocket.CLOSED);
		const unregister = invalidator.register(TEST_SESSION_ID, socket);
		unregister();

		await valkey.publish(
			SESSION_INVALIDATION_CHANNEL,
			JSON.stringify({ session_id: TEST_SESSION_ID, reason: "UserLogout" }),
		);
		await new Promise((resolve) => setTimeout(resolve, 150));

		expect(socket.send).not.toHaveBeenCalled();
		expect(socket.close).not.toHaveBeenCalled();
	});
});

describe("end-to-end: real server dispatches SessionReplaced then closes 4001", () => {
	let valkey: Redis;
	let handle: RealtimeServerHandle;
	let wsUrl: string;

	beforeEach(async () => {
		valkey = new Redis(VALKEY_URL);
		await valkey.flushdb();
		handle = startRealtimeServer({ port: 0, valkeyUrl: VALKEY_URL });
		await once(handle.server, "listening");
		const address = handle.server.address() as AddressInfo;
		wsUrl = `ws://127.0.0.1:${address.port}`;
	});

	afterEach(async () => {
		await handle.close();
		valkey.disconnect();
	});

	it("sends the frame and closes the live connection with code 4001", async () => {
		const seeded = {
			session_id: TEST_SESSION_ID,
			account_id: "00000000-0000-0000-0000-00000000000a",
			device_id: "device-1",
			status: "Active",
			expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
			last_strong_auth_at: new Date(Date.now() - 60_000).toISOString(),
		};
		await valkey.set(`session:${TEST_SESSION_ID}`, JSON.stringify(seeded));

		const client = new WebSocket(wsUrl, {
			headers: { Cookie: `${SESSION_COOKIE_NAME}=${TEST_SESSION_ID}` },
		});
		await once(client, "open");

		await valkey.publish(
			SESSION_INVALIDATION_CHANNEL,
			JSON.stringify({ session_id: TEST_SESSION_ID, reason: "NewDeviceLogin" }),
		);

		const [frame, closeInfo] = await Promise.all([
			once(client, "message").then(([data]) => data),
			once(client, "close"),
		]);
		client.terminate();

		const parsed = JSON.parse(String(frame)) as SessionReplacedFrame;
		expect(parsed.type).toBe("SessionReplaced");
		expect(parsed.message).toBe("当前账号已在另一台设备登录");
		expect(closeInfo[0]).toBe(SESSION_REPLACED_CLOSE_CODE);
	});
});
