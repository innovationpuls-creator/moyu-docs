/**
 * /editor page: minimal placeholder editor that exercises the Phase 9 browser
 * session semantics (UI/UX neutral):
 *
 * - a textarea whose content is persisted to localStorage under
 *   DRAFT_STORAGE_KEY on every input (the "unsynced draft");
 * - a realtime WebSocket connection through @dom/realtime-client ONLY
 *   (no feature-level WebSocket creation — doc 27 dependency direction);
 * - on the gateway's session-replaced signal (close code 4001) it shows a
 *   NON-CLOSABLE session-replaced dialog with a re-login entry (FR-AUTH-017)
 *   and — when an unsynced draft exists — a draft-recovery banner that keeps
 *   the content visible and exportable (FR-AUTH-019), so local edits are never
 *   silently discarded.
 */

import { connectRealtime } from "@dom/realtime-client";

import { navigate } from "../main";

export const DRAFT_STORAGE_KEY = "draft_unsaved";
const REALTIME_URL =
	import.meta.env.VITE_REALTIME_URL ?? "ws://localhost:8765/v1/realtime";

export async function renderEditorPage(app: HTMLElement): Promise<void> {
	app.replaceChildren();

	// Session gate on mount: an invalid/replaced session must not resume the
	// editor (FR-AUTH-021 AC-021.2 — refresh of a dead session -> login page).
	const { DomClient } = await import("@dom/client-sdk");
	if ((await new DomClient().me()) === null) {
		navigate("/login");
		return;
	}

	const heading = document.createElement("h1");
	heading.textContent = "编辑器占位页";

	const draft = document.createElement("textarea");
	draft.dataset.testid = "editor-draft-textarea";
	draft.value = readDraft();
	draft.addEventListener("input", () => {
		writeDraft(draft.value);
	});

	const hint = document.createElement("p");
	hint.textContent = "本地未同步草稿将保存在此浏览器中";

	// Functional realtime connection status (E2E waits for "connected" before
	// driving the replacement so the socket is provably live).
	const status = document.createElement("p");
	status.dataset.testid = "realtime-status";
	status.textContent = "connecting";

	app.append(heading, hint, draft, status);

	// Draft-recovery banner: visible after a replacement while an unsynced
	// draft exists; content stays readable and exportable (never discarded).
	const banner = document.createElement("section");
	banner.hidden = true;
	banner.dataset.testid = "draft-recovery-banner";

	const bannerTitle = document.createElement("h2");
	bannerTitle.textContent = "检测到本地未同步草稿";

	const bannerContent = document.createElement("pre");
	bannerContent.dataset.testid = "draft-recovery-content";

	const exportButton = document.createElement("button");
	exportButton.type = "button";
	exportButton.textContent = "导出草稿";
	exportButton.dataset.testid = "draft-export-button";
	exportButton.addEventListener("click", () => {
		exportDraft(bannerContent.textContent ?? "");
	});

	banner.append(bannerTitle, bannerContent, exportButton);

	// Session-replaced dialog: non-closable (no dismiss control); the only
	// action is re-login (FR-AUTH-017 BDD "提示区分于普通网络故障" — distinct
	// workflow from an ordinary network-error path). The draft-recovery banner
	// lives INSIDE the dialog when a replacement fires: a <dialog> opened via
	// showModal() makes the rest of the page inert, so the export button must
	// be part of the modal to stay usable.
	const dialog = document.createElement("dialog");
	dialog.dataset.testid = "session-replaced-dialog";
	dialog.addEventListener("cancel", (event) => {
		// Non-closable: user must re-login before continuing.
		event.preventDefault();
	});
	const dialogTitle = document.createElement("h2");
	dialogTitle.textContent = "当前账号已在另一台设备登录，本设备已下线";
	const dialogBody = document.createElement("p");
	dialogBody.textContent = "本设备已下线。您可以重新登录以继续。";
	const relogin = document.createElement("button");
	relogin.type = "button";
	relogin.textContent = "重新登录";
	relogin.dataset.testid = "session-replaced-relogin";
	relogin.addEventListener("click", () => {
		navigate("/login");
	});
	dialog.append(dialogTitle, dialogBody, relogin);

	app.append(banner, dialog);

	// On mount, surface an existing unsynced draft so a re-login or fresh
	// navigation never hides it (FR-AUTH-019: draft stays recoverable/
	// exportable until the user acts on it).
	const initial = readDraft();
	if (initial.length > 0) {
		bannerContent.textContent = initial;
		banner.hidden = false;
	}

	const realtime = connectRealtime(REALTIME_URL);
	realtime.socket.addEventListener("open", () => {
		status.textContent = "connected";
	});
	realtime.socket.addEventListener("close", (event) => {
		status.textContent =
			event.code === 4001 ? "closed:4001" : `closed:${event.code}`;
	});
	realtime.onSessionReplaced((detail) => {
		const unsynced = readDraft();
		if (unsynced.length > 0 && !dialog.contains(banner)) {
			// Move the recovery banner into the modal so its export control
			// stays interactive while the page behind the dialog is inert.
			bannerContent.textContent = unsynced;
			banner.hidden = false;
			dialog.prepend(banner);
		}
		if (!dialog.open) {
			dialog.showModal();
		}
		// Keep the detail observable for diagnostics (closeCode 4001).
		console.info("[dom/web] session replaced:", detail);
	});

	// On refresh after a replacement the cookie no longer authenticates; the
	// realtime handshake is rejected and the session query redirects to login.
	realtime.socket.addEventListener("close", (event) => {
		if (event.code !== 4001 && !dialog.open) {
			void (async () => {
				const { DomClient } = await import("@dom/client-sdk");
				if ((await new DomClient().me()) === null) {
					navigate("/login");
				}
			})();
		}
	});
}

export function readDraft(): string {
	return window.localStorage.getItem(DRAFT_STORAGE_KEY) ?? "";
}

export function writeDraft(content: string): void {
	window.localStorage.setItem(DRAFT_STORAGE_KEY, content);
}

function exportDraft(content: string): void {
	const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement("a");
	anchor.href = url;
	anchor.download = "dom-draft.txt";
	anchor.click();
	URL.revokeObjectURL(url);
}
