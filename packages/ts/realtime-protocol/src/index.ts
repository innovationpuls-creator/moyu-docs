import type {
	RealtimeSyncFrameHeader,
	RealtimeSyncMessageType,
} from "@dom/contracts/realtime/frame-header";

const MAGIC = new Uint8Array([0x44, 0x4d]);
const HEADER_SIZE = 6;
const PROTOCOL_VERSION = 1;

export type SyncMessageType = RealtimeSyncMessageType;

export type RealtimeBinaryHeader = RealtimeSyncFrameHeader;

export interface RealtimeBinaryFrame {
	header: RealtimeBinaryHeader;
	payload: Uint8Array;
}

export function encodeRealtimeBinaryFrame(
	header: Pick<
		RealtimeSyncFrameHeader,
		"messageType" | "resourceId" | "subscriptionId"
	>,
	payload: Uint8Array,
): Uint8Array {
	const fullHeader: RealtimeBinaryHeader = {
		protocolVersion: PROTOCOL_VERSION,
		frameType: "Sync",
		payloadKind: "binary",
		...header,
	};
	const headerBytes = new TextEncoder().encode(JSON.stringify(fullHeader));
	if (headerBytes.byteLength > 65_535) {
		throw new RangeError("Realtime frame header is too large");
	}
	const frame = new Uint8Array(
		HEADER_SIZE + headerBytes.byteLength + payload.byteLength,
	);
	frame.set(MAGIC, 0);
	frame[2] = PROTOCOL_VERSION;
	frame[3] = header.messageType === "sync.update" ? 1 : 2;
	new DataView(frame.buffer).setUint16(4, headerBytes.byteLength, false);
	frame.set(headerBytes, HEADER_SIZE);
	frame.set(payload, HEADER_SIZE + headerBytes.byteLength);
	return frame;
}

export function decodeRealtimeBinaryFrame(
	input: ArrayBuffer | Uint8Array,
): RealtimeBinaryFrame {
	const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
	if (
		bytes.byteLength < HEADER_SIZE ||
		bytes[0] !== MAGIC[0] ||
		bytes[1] !== MAGIC[1]
	) {
		throw new TypeError("Invalid realtime binary frame magic");
	}
	if (bytes[2] !== PROTOCOL_VERSION) {
		throw new TypeError(`Unsupported realtime protocol version ${bytes[2]}`);
	}
	const headerLength = new DataView(
		bytes.buffer,
		bytes.byteOffset,
		bytes.byteLength,
	).getUint16(4, false);
	const payloadOffset = HEADER_SIZE + headerLength;
	if (payloadOffset > bytes.byteLength) {
		throw new TypeError("Realtime frame header is truncated");
	}
	const raw = JSON.parse(
		new TextDecoder().decode(bytes.subarray(HEADER_SIZE, payloadOffset)),
	) as Partial<RealtimeBinaryHeader>;
	const messageType =
		bytes[3] === 1
			? "sync.update"
			: bytes[3] === 2
				? "sync.state-vector"
				: null;
	if (
		messageType === null ||
		raw.protocolVersion !== PROTOCOL_VERSION ||
		raw.frameType !== "Sync" ||
		raw.payloadKind !== "binary" ||
		raw.messageType !== messageType ||
		typeof raw.resourceId !== "string" ||
		typeof raw.subscriptionId !== "string"
	) {
		throw new TypeError("Realtime frame header is invalid");
	}
	return {
		header: raw as RealtimeBinaryHeader,
		payload: bytes.slice(payloadOffset),
	};
}
