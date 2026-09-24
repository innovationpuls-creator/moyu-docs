/* eslint-disable */
/**
 * Generated from /contracts by scripts/generate_ts_contracts.mjs.
 * Do not edit; run `just contract` instead.
 */

export type FolderId = string;
export type IdempotencyKey = string;

/**
 * FR-WRL-008. Restore Folder ancestor lifecycle and all descendant metadata state atomically. A missing/inaccessible old parent falls back to Project root; a sibling conflict generates `Name (restored N).ext`, lowest available positive N, preserving final extension. Current Permission is reevaluated; no Purge occurs.
 */
export interface RestoreFolder {
	folderId: FolderId;
	idempotencyKey: IdempotencyKey;
}
