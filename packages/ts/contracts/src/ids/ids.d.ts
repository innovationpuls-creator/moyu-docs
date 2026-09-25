/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;
export type WorkspaceId = string;
export type ProjectId = string;
export type FolderId = string;
export type ResourceId = string;
export type ChangeSetId = string;
export type NodeId = string;
export type TaskId = string;
export type AttemptId = string;
export type CommentId = string;
export type ThreadId = string;
export type AssetId = string;
export type EventId = string;
export type RequestId = string;
export type OperationId = string;
export type SessionId = string;
export type SubscriptionId = string;
export type DeliveryId = string;
export type IdempotencyKey = string;
export type AccountStatusValue =
	| "PendingVerification"
	| "Active"
	| "Disabled"
	| "DeletionPending"
	| "Deleted";
export type SessionStatusValue =
	| "Active"
	| "Replaced"
	| "LoggedOut"
	| "Expired"
	| "Revoked";
export type SessionReplacementReason =
	| "NewDeviceLogin"
	| "UserLogout"
	| "PasswordReset"
	| "AccountDisabled"
	| "Expired"
	| "SecurityRevoke";

/**
 * Canonical ID types plus shared cross-contract value enums (doc 28 §9-§11). The ID types (UserId, WorkspaceId, ProjectId, FolderId, ResourceId, NodeId, TaskId, AttemptId, CommentId, ThreadId, AssetId, EventId, RequestId, OperationId, SessionId, SubscriptionId, DeliveryId, IdempotencyKey, NodeRef) use UUIDv7. The shared value enums AccountStatusValue, SessionStatusValue and SessionReplacementReason are co-located here (doc 27 §52 freezes no directory for shared enums) so their generated class names stay globally unique across the contract tree — one canonical definition, referenced everywhere via $ref. The registry logical name IdentityIds therefore covers both the ID types and these shared value enums. The root is the identity surface manifest: one property per canonical ID type, declared so that every ID type is projected in every target language (doc 28 §42/§46). It is not a transport payload and no field is required.
 */
export interface IdentityIds {
	userId?: UserId;
	workspaceId?: WorkspaceId;
	projectId?: ProjectId;
	folderId?: FolderId;
	resourceId?: ResourceId;
	changesetId?: ChangeSetId;
	nodeId?: NodeId;
	taskId?: TaskId;
	attemptId?: AttemptId;
	commentId?: CommentId;
	threadId?: ThreadId;
	assetId?: AssetId;
	eventId?: EventId;
	requestId?: RequestId;
	operationId?: OperationId;
	sessionId?: SessionId;
	subscriptionId?: SubscriptionId;
	deliveryId?: DeliveryId;
	idempotencyKey?: IdempotencyKey;
	accountStatusValue?: AccountStatusValue;
	sessionStatusValue?: SessionStatusValue;
	sessionReplacementReason?: SessionReplacementReason;
	nodeRef?: NodeRef;
}
export interface NodeRef {
	resourceId: ResourceId;
	nodeId: NodeId;
}
