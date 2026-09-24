/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type UserId = string;

/**
 * Arch 10 dead-letter replay: requeue the newest Failed delivery as a fresh Queued task.
 */
export interface RequeueWebhookDeliveries {
	webhookId: UserId;
}
