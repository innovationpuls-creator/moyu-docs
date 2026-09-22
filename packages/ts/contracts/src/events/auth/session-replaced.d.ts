/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type EventId = string;
export type UserId = string;
export type WorkspaceId = string;
export type ResourceId = string;
export type SessionId = string;
export type SessionReplacementReason =
	| "NewDeviceLogin"
	| "UserLogout"
	| "PasswordReset"
	| "AccountDisabled"
	| "Expired"
	| "SecurityRevoke";

/**
 * doc 28 §22 EventEnvelope shape + replacement facts. eventSubject = event.auth.session-replaced.v1 (doc 28 §25). The root IS the envelope; the payload carries the replacement facts. Secrets/credentials are never present (doc 28 §58).
 */
export interface SessionReplaced {
	eventId: EventId;
	eventType: "SessionReplaced";
	schemaVersion: string;
	occurredAt: string;
	producer: string;
	traceId?: string;
	actorRef?: UserId;
	workspaceId?: WorkspaceId;
	resourceId?: ResourceId;
	payload: SessionReplacedPayload;
}
export interface SessionReplacedPayload {
	userId: UserId;
	replacedSessionId: SessionId;
	replacedBySessionId: SessionId;
	invalidationReason: SessionReplacementReason;
	replacedAt: string;
}
