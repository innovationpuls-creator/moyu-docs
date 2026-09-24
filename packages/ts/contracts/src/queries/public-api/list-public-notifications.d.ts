/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;

/**
 * PUB-001. Machine-client notifications list, authenticated by an integration key (Ed25519 signature headers; no session).
 */
export interface GetPublicNotificationsResponse {
	items: {
		notificationId: UserId;
		kind: string;
		payload: {};
		readAt: string | null;
	}[];
}
