/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * A Resource-scoped comment event delivered on the authenticated Realtime subscription.
 */
export type CommentRealtimeEvent =
	| CommentAddedFrame
	| CommentEditedFrame
	| CommentDeletedFrame
	| ThreadResolvedFrame
	| ThreadReopenedFrame;
export type ResourceId = string;
export type SubscriptionId = string;
export type CommentId = string;
export type ThreadId = string;
export type UserId = string;
export type ThreadResolvedPayload = ThreadTransitionPayload & {
	status: "Resolved";
};
export type ThreadReopenedPayload = ThreadTransitionPayload & {
	status: "Open";
};

export interface CommentAddedFrame {
	protocolVersion: 1;
	subject: string;
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
	kind: "comment.added";
	payload: CommentAddedPayload;
	sequence?: number | null;
	occurredAt: string;
}
export interface CommentAddedPayload {
	resourceId: ResourceId;
	commentId: CommentId;
	threadId: ThreadId;
	author: UserId;
	body: string;
}
export interface CommentEditedFrame {
	protocolVersion: 1;
	subject: string;
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
	kind: "comment.edited";
	payload: CommentEditedPayload;
	sequence?: number | null;
	occurredAt: string;
}
export interface CommentEditedPayload {
	commentId: CommentId;
	body: string;
}
export interface CommentDeletedFrame {
	protocolVersion: 1;
	subject: string;
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
	kind: "comment.deleted";
	payload: CommentDeletedPayload;
	sequence?: number | null;
	occurredAt: string;
}
export interface CommentDeletedPayload {
	commentId: CommentId;
}
export interface ThreadResolvedFrame {
	protocolVersion: 1;
	subject: string;
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
	kind: "ThreadResolved";
	payload: ThreadResolvedPayload;
	sequence?: number | null;
	occurredAt: string;
}
export interface ThreadTransitionPayload {
	threadId: ThreadId;
	resourceId: ResourceId;
	status: "Open" | "Resolved";
	resolvedBy: UserId | null;
	resolvedAt: string | null;
}
export interface ThreadReopenedFrame {
	protocolVersion: 1;
	subject: string;
	resourceId: ResourceId;
	subscriptionId: SubscriptionId;
	kind: "ThreadReopened";
	payload: ThreadReopenedPayload;
	sequence?: number | null;
	occurredAt: string;
}
