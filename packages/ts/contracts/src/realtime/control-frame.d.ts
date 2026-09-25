/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type RealtimeControlFrameHeader = RealtimeFrameHeaderBase & {
	frameType: "Control";
	payloadKind: "json";
	messageType: RealtimeControlMessageType;
};
export type ResourceId = string;
export type SubscriptionId = string;
export type RequestId = string;
export type RealtimeControlMessageType =
	| "connect"
	| "ready"
	| "subscribe"
	| "subscribed"
	| "unsubscribe"
	| "permission"
	| "schema"
	| "error"
	| "ping"
	| "pong";

/**
 * Reliable low-frequency Control envelope. Message-specific payload fields remain defined by the owning control operation.
 */
export interface RealtimeControlFrame {
	header: RealtimeControlFrameHeader;
	/**
	 * Operation-specific Control payload; its fields are validated by the corresponding operation contract.
	 */
	payload: {
		[k: string]: unknown;
	};
}
export interface RealtimeFrameHeaderBase {
	protocolVersion: 1;
	frameType: "Control" | "Sync" | "Awareness" | "System";
	messageType: string;
	payloadKind: "binary" | "json";
	resourceId?: ResourceId;
	subscriptionId?: SubscriptionId;
	requestId?: RequestId;
	acceptedWatermark?: number;
	durableWatermark?: number;
}
