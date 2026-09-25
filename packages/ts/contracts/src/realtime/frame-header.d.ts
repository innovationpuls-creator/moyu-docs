/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * Common WebSocket frame routing header. Resource and subscription identity are required for Resource-scoped Sync and Awareness frames.
 */
export type RealtimeFrameHeader =
	| RealtimeControlFrameHeader
	| RealtimeSyncFrameHeader
	| RealtimeAwarenessFrameHeader
	| RealtimeSystemFrameHeader;
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
export type RealtimeSyncFrameHeader = RealtimeFrameHeaderBase & {
	frameType: "Sync";
	payloadKind: "binary";
	messageType: RealtimeSyncMessageType;
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
};
export type RealtimeSyncMessageType = "sync.update" | "sync.state-vector";
export type RealtimeAwarenessFrameHeader = RealtimeFrameHeaderBase & {
	frameType: "Awareness";
	payloadKind: "binary";
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
};
export type RealtimeSystemFrameHeader = RealtimeFrameHeaderBase & {
	frameType: "System";
	payloadKind: "json";
};

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
