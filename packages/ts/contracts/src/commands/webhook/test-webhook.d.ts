/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

/**
 * FR-WEB-004. Deliver a webhook.test event to the endpoint and report the result (no body).
 */
export interface TestWebhookResponse {
	delivered: boolean;
	statusCode: number;
}
