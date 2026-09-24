/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-NTF-003. Mark one notification read (no body).
 */
export interface MarkNotificationReadResponse {
	notificationId: string;
	readAt: string;
}
