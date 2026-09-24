/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;

/**
 * FR-NTF-001. In-app notifications, newest first.
 */
export interface ListNotificationsResponse {
	items: {
		notificationId: UserId;
		kind: string;
		payload: {};
		createdAt: string | null;
		readAt: string | null;
	}[];
	unreadCount: number;
}
