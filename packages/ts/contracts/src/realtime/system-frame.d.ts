/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type RealtimeSystemFrameHeader = RealtimeFrameHeaderBase & {
	frameType: "System";
	payloadKind: "json";
};
export type ResourceId = string;
export type SubscriptionId = string;
export type RequestId = string;

/**
 * System envelope for service-health and protocol-maintenance messages; it carries no document-content semantics.
 */
export interface RealtimeSystemFrame {
	header: RealtimeSystemFrameHeader;
	/**
	 * System message-specific fields; exact fields are owned by each system message definition.
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
