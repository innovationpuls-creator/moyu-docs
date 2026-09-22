/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type AuthErrorCategory =
	| "Validation"
	| "Authentication"
	| "Permission"
	| "NotFound"
	| "Conflict"
	| "RateLimit"
	| "Timeout"
	| "DependencyFailure"
	| "Unavailable"
	| "Internal";
export type ErrorCode = string;
export type MessageKey = string;
export type ErrorMessage = string;
export type RequestId = string;
export type Retryable = boolean;
export type FieldName = string;
export type FieldErrorCode = string;
export type FieldMessage = string;
export type FieldErrors = FieldError[];

/**
 * Canonical error envelope (doc 28 §29). The root object IS the envelope; it is referenced directly by OpenAPI error responses. category is one of the ten canonical categories from doc 04 §23 / Constitution §3.19; errorCode matches ^[A-Z0-9_]+$; requestId is a UUIDv7; fieldErrors carries field-level validation detail.
 */
export interface ErrorEnvelope {
	category: AuthErrorCategory;
	errorCode: ErrorCode;
	messageKey: MessageKey;
	message?: ErrorMessage;
	requestId: RequestId;
	retryable: Retryable;
	fieldErrors?: FieldErrors;
	details?: ErrorDetails;
}
export interface FieldError {
	field: FieldName;
	code: FieldErrorCode;
	message: FieldMessage;
}
/**
 * Safe, structured business detail only. Must never contain stack traces, SQL, internal hosts, secrets or provider tokens (doc 28 §31).
 */
export interface ErrorDetails {
	[k: string]: unknown;
}
