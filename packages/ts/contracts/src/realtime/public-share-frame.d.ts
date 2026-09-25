/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * Token-authenticated read-only Resource subscription for an active public share link.
 */
export type PublicShareRealtimeFrame =
	| AuthenticateShareFrame
	| ShareAuthenticatedFrame
	| ShareStateFrame;
export type ResourceId = string;
export type SubscriptionId = string;

export interface AuthenticateShareFrame {
	protocolVersion: 1;
	type: "authenticate-share";
	token: string;
}
export interface ShareAuthenticatedFrame {
	protocolVersion: 1;
	type: "share-authenticated";
	payload: ShareAuthenticatedPayload;
}
export interface ShareAuthenticatedPayload {
	status: "ok";
}
export interface ShareStateFrame {
	protocolVersion: 1;
	type: "share-state";
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
	payload: ShareStatePayload;
}
export interface ShareStatePayload {
	stateKind: "yjs" | "checkpoint";
}
