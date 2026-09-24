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

	// Resource vertical: /editor?resource=<id> loads the snapshot through the
	// client SDK (agents never fetch directly) and renders it read-only under
	// a typed error surface (404/403 -> message; SDK errors are shaped).
	const params = new URLSearchParams(window.location.search);
	const resourceId = params.get("resource");
	// Live body CRDT + presence (arch 05): declared at function scope because
	// the draft textarea is unconditional while the realtime pieces only exist
	// when a resource is open. The listener binds at the draft creation site.
	let liveDocumentP:
		| Promise<import("@dom/yjs-runtime").DocumentHandle>
		| undefined;
	let publishYjsImpl: (() => void) | undefined;
	let yjsLiveTimer: ReturnType<typeof setTimeout> | undefined;
	let idleLiveTimer: ReturnType<typeof setTimeout> | undefined;
	const presence = document.createElement("p");
	presence.dataset.testid = "editor-presence";
	presence.textContent = "";
	const roster = document.createElement("p");
	roster.dataset.testid = "editor-roster";
	roster.textContent = "";
	// arch 05 roster click-through: expand the live peer presence on demand.
	roster.addEventListener("click", () => {
		presence.hidden = !presence.hidden;
		roster.dataset.expanded = presence.hidden ? "false" : "true";
	});
	let channelLive:
		| import("@dom/realtime-client").ResourceChannelClient
		| undefined;
	const firstResourceId = resourceId ?? "";
	const publishPresence = (typing: boolean): void => {
		let cursor: number | undefined;
		const box = document.querySelector<HTMLTextAreaElement>(
			"[data-testid=editor-draft-textarea]",
		);
		if (box && typing) cursor = box.selectionStart;
		if (typing) {
			presence.textContent =
				cursor === undefined ? "正在编辑…" : `正在编辑…（光标 @${cursor}）`;
		} else presence.textContent = "";
		if (channelLive && firstResourceId) {
			channelLive.publishOp(firstResourceId, {
				kind: "presence",
				typing,
				...(cursor !== undefined ? { cursor } : {}),
			});
		}
	};
	const writeDraftListener = (): void => {
		const box = document.querySelector<HTMLTextAreaElement>(
			"[data-testid=editor-draft-textarea]",
		);
		if (box) writeDraft(box.value);
	};
	const resourcePanel = document.createElement("section");
	resourcePanel.dataset.testid = "resource-panel";
	if (resourceId !== null) {
		const { DomClient } = await import("@dom/client-sdk");
		try {
			const resource = await new DomClient().openResource(resourceId);
			const name = document.createElement("h2");
			name.dataset.testid = "resource-name";
			name.textContent = resource.name;
			const snapshot = document.createElement("pre");
			snapshot.dataset.testid = "resource-snapshot";
			snapshot.textContent =
				resource.snapshot === null
					? "（无快照）"
					: JSON.stringify(resource.snapshot, null, 2);
			resourcePanel.append(name, snapshot);
		} catch (error) {
			const message = document.createElement("p");
			message.dataset.testid = "resource-error";
			message.textContent =
				error instanceof Error ? error.message : String(error);
			resourcePanel.append(message);
		}
		// Save vertical: append the draft as one journal op through the SDK
		// (feature code never fetches); status surfaces the authoritative seq.
		const save = document.createElement("button");
		save.type = "button";
		save.dataset.testid = "editor-save";
		save.textContent = "保存";
		const status = document.createElement("p");
		status.dataset.testid = "editor-save-status";
		save.addEventListener("click", () => {
			void (async () => {
				try {
					const { DomClient } = await import("@dom/client-sdk");
					// Body CRDT (arch 05): the draft is set on a Y.Text document
					// so the SAVED text is the merged CRDT state; local Yjs
					// updates stay available for the future realtime transport.
					const { createDocument, setText } = await import("@dom/yjs-runtime");
					const documentHandle = createDocument();
					setText(documentHandle, readDraft());
					const merged = documentHandle.text();
					const result = await new DomClient().appendJournalOp(resourceId, {
						update: btoa(unescape(encodeURIComponent(merged))),
						expectedSeq: 1,
						idempotencyKey: crypto.randomUUID(),
					});
					status.textContent = `已保存（journalSeq=${result.journalSeq}）`;
					void renderHistory();
				} catch (error) {
					status.textContent =
						error instanceof Error ? error.message : String(error);
				}
			})();
		});
		// Realtime: subscribe to the resource channel; render echoed/peer ops.
		const incoming = document.createElement("ul");
		incoming.dataset.testid = "editor-incoming-ops";
		const { connectRealtime } = await import("@dom/realtime-client");
		const { ResourceChannelClient } = await import("@dom/realtime-client");
		const rt = connectRealtime(REALTIME_URL);
		// Best-effort: never block rendering on the socket; subscribe when open
		// (or shortly after) and drop silently if the gateway is unreachable.
		const channel = new ResourceChannelClient(
			rt.socket as unknown as {
				send(data: string): void;
				close(): void;
				onmessage: ((event: { data: string | ArrayBuffer }) => void) | null;
			},
		);
		channelLive = channel;
		channel.attach();
		// Live body CRDT (arch 05 §171): the local Yjs document is the source of
		// truth for typing; updates are published to peers (debounced) and remote
		// updates merge into the local doc + textarea. The input listener binds
		// to the textarea at its creation site further down (the DOM does not
		// exist yet at this point).
		liveDocumentP = import("@dom/yjs-runtime").then((m) => m.createDocument());
		publishYjsImpl = (): void => {
			void liveDocumentP?.then((doc) => {
				for (const update of doc.flushUpdates()) {
					channel.publishOp(resourceId, {
						kind: "yjs",
						update: btoa(String.fromCharCode(...update)),
					});
				}
			});
		};
		let peerYjsTimer: ReturnType<typeof setTimeout> | undefined;
		channel.onAny((message) => {
			console.error("[dom-editor] any", JSON.stringify(message));
			if (
				message.type === "subscribe" &&
				typeof message.payload === "object" &&
				message.payload !== null &&
				"status" in message.payload &&
				(message.payload as { status: string }).status === "ok"
			) {
				resourcePanel.dataset.subscribed = "true";
			}
		});
		const trySubscribe = (): void => {
			if (rt.socket?.readyState === WebSocket.OPEN) {
				channel.subscribe(resourceId);
				// arch 05 §172: ask the gateway for exactly the missing tail via
				// our current state-vector (incremental catch-up).
				void liveDocumentP?.then((doc) => {
					channel.publishSync(
						resourceId,
						btoa(String.fromCharCode(...doc.stateVector())),
					);
				});
			}
		};
		rt.socket?.addEventListener("open", () => trySubscribe(), { once: true });
		setTimeout(trySubscribe, 400);
		channel.onResource(resourceId, (message) => {
			console.error(
				"[dom-editor] res",
				message.type,
				JSON.stringify(message.payload),
			);
			if (
				message.type === "comment.added" ||
				message.type === "comment.edited" ||
				message.type === "comment.deleted"
			) {
				const row = document.createElement("li");
				row.dataset.testid = "live-comment-row";
				const payload = message.payload as {
					body?: string;
					commentId?: string;
				} | null;
				if (message.type === "comment.deleted") {
					row.textContent = `评论已删除: ${payload?.commentId ?? "?"}`;
				} else {
					row.textContent = `${message.type === "comment.edited" ? "评论已编辑" : "实时评论"}: ${payload?.body ?? "?"}`;
				}
				incoming.append(row);
				void renderComments();
				return;
			}
			if (
				message.type === "op" &&
				typeof message.payload === "object" &&
				message.payload !== null &&
				(message.payload as { kind?: string }).kind === "roster"
			) {
				const peers = (message.payload as { peers?: number }).peers;
				roster.textContent = `${peers ?? 0} 人在线`;
				return;
			}
			if (
				message.type === "op" &&
				typeof message.payload === "object" &&
				message.payload !== null &&
				(message.payload as { kind?: string }).kind === "presence"
			) {
				const typing = (message.payload as { typing?: boolean }).typing;
				const cursor = (message.payload as { cursor?: number }).cursor;
				presence.textContent = typing
					? cursor === undefined
						? "正在编辑…"
						: `对方正在编辑…（光标 @${cursor}）`
					: "";
				return;
			}
			if (
				message.type === "op" &&
				typeof message.payload === "object" &&
				message.payload !== null &&
				(message.payload as { kind?: string }).kind === "yjs" &&
				typeof (message.payload as { update?: string }).update === "string"
			) {
				const update = (message.payload as { update: string }).update;
				const bytes = Uint8Array.from(atob(update), (c) => c.charCodeAt(0));
				void liveDocumentP?.then((doc) => {
					doc.applyRemoteUpdate(bytes);
					const merged = doc.text();
					const box = document.querySelector<HTMLTextAreaElement>(
						"[data-testid=editor-draft-textarea]",
					);
					if (box && box.value !== merged) {
						box.value = merged;
					}
					void renderComments();
					void renderHistory();
				});
				if (peerYjsTimer) clearTimeout(peerYjsTimer);
				peerYjsTimer = setTimeout(() => publishYjsImpl?.(), 300);
				return;
			}
			if (message.type !== "op") return;
			const li = document.createElement("li");
			const seq =
				typeof message.payload === "object" &&
				message.payload !== null &&
				"journalSeq" in message.payload
					? String((message.payload as { journalSeq: number }).journalSeq)
					: "?";
			li.textContent = `op${seq}`;
			incoming.append(li);
		});
		// Comments panel (arch 17): list + add + reply through the SDK.
		const commentsSection = document.createElement("section");
		commentsSection.dataset.testid = "comments-panel";
		const commentsList = document.createElement("ul");
		commentsList.dataset.testid = "comments-list";
		const commentInput = document.createElement("input");
		commentInput.dataset.testid = "comment-input";
		commentInput.placeholder = "写评论…（@ 提及成员）";
		const mentionPicker = document.createElement("ul");
		mentionPicker.dataset.testid = "mention-picker";
		const renderMentions = async (prefix: string): Promise<void> => {
			mentionPicker.replaceChildren();
			try {
				const { DomClient } = await import("@dom/client-sdk");
				const workspaces = await new DomClient().listWorkspaces();
				const targetWorkspace = workspaces.workspaces[0]?.workspaceId ?? "";
				if (!targetWorkspace) return;
				const needle = prefix.length > 0 ? prefix : "@";
				const suggestions = await new DomClient().suggestMembers(
					targetWorkspace,
					needle,
				);
				for (const member of suggestions.suggestions) {
					const option = document.createElement("li");
					option.dataset.testid = "mention-option";
					option.textContent = member.email;
					option.addEventListener("click", (event) => {
						event.stopPropagation();
						commentInput.value = commentInput.value.replace(
							/@[\w.+-]*$/,
							`@${member.email}`,
						);
						mentionPicker.replaceChildren();
					});
					mentionPicker.append(option);
				}
			} catch {
				mentionPicker.replaceChildren();
			}
		};
		commentInput.addEventListener("input", (event) => {
			const value = (event.target as HTMLInputElement).value;
			const match = /@([\w.+-]*)$/.exec(value);
			void renderMentions(match?.[1] ?? "");
		});
		const commentAdd = document.createElement("button");
		commentAdd.type = "button";
		commentAdd.dataset.testid = "comment-submit";
		commentAdd.textContent = "评论";
		const commentStatus = document.createElement("p");
		commentStatus.dataset.testid = "comment-status";
		let activeThreadId: string | null = null;
		const renderComments = async (): Promise<void> => {
			try {
				const { DomClient } = await import("@dom/client-sdk");
				const result = await new DomClient().listComments(resourceId);
				commentsList.replaceChildren();
				for (const comment of result.items) {
					const row = document.createElement("li");
					row.dataset.testid = "comment-row";
					row.textContent = comment.body;
					if (
						comment.anchor &&
						typeof comment.anchor === "object" &&
						"text" in comment.anchor &&
						typeof comment.anchor.text === "string"
					) {
						const anchorNote = document.createElement("small");
						anchorNote.dataset.testid = "comment-anchor";
						anchorNote.textContent = `引用: ${comment.anchor.text}`;
						// arch 12 §anchors: click the quoted text to jump to the
						// matching span inside the draft and focus it.
						anchorNote.addEventListener("click", (event) => {
							event.stopPropagation();
							const draftEl = document.querySelector<HTMLTextAreaElement>(
								"[data-testid=editor-draft-textarea]",
							);
							if (!draftEl) return;
							const needle = String(comment.anchor.text);
							const at = draftEl.value.indexOf(needle);
							if (at >= 0) {
								draftEl.focus();
								draftEl.setSelectionRange(at, at + needle.length);
							}
							row.scrollIntoView({ behavior: "smooth", block: "center" });
							row.dataset.jumped = "true";
						});
						row.append(document.createElement("br"), anchorNote);
					}
					row.addEventListener("click", (event) => {
						event.stopPropagation();
						activeThreadId = comment.threadId;
						commentInput.placeholder = "回复…";
					});
					commentsList.append(row);
				}
			} catch {
				commentsList.replaceChildren();
			}
		};
		void renderComments();
		commentAdd.addEventListener("click", (event) => {
			event.stopPropagation();
			void (async () => {
				try {
					const { DomClient } = await import("@dom/client-sdk");
					const result = await new DomClient().addComment(resourceId, {
						body: commentInput.value,
						...(activeThreadId ? { threadId: activeThreadId } : {}),
						idempotencyKey: crypto.randomUUID(),
					});
					commentStatus.textContent = `已评论（${result.commentId}）`;
					commentInput.value = "";
					await renderComments();
				} catch (error) {
					commentStatus.textContent =
						error instanceof Error ? error.message : String(error);
				}
			})();
		});
		commentsSection.append(
			commentsList,
			commentInput,
			mentionPicker,
			commentAdd,
			commentStatus,
		);
		// AI changesets (arch 21): propose an instruction (dev provider returns
		// a canned suggestion) and apply it; the panel records the outcomes.
		const aiSection = document.createElement("section");
		aiSection.dataset.testid = "ai-panel";
		const aiInstruction = document.createElement("input");
		aiInstruction.dataset.testid = "ai-instruction";
		aiInstruction.placeholder = "AI 改动指令…";
		const aiPropose = document.createElement("button");
		aiPropose.type = "button";
		aiPropose.dataset.testid = "ai-propose";
		aiPropose.textContent = "生成变更";
		const aiResult = document.createElement("p");
		aiResult.dataset.testid = "ai-changeset-status";
		aiResult.textContent = "";
		aiPropose.addEventListener("click", (event) => {
			event.stopPropagation();
			void (async () => {
				const { DomClient } = await import("@dom/client-sdk");
				const proposed = await new DomClient().proposeChangeSet(
					resourceId,
					aiInstruction.value,
				);
				aiResult.textContent = `变更集 ${proposed.changesetId} - ${proposed.status}`;
				const applied = await new DomClient().applyChangeSet(
					proposed.changesetId,
				);
				aiResult.textContent = `变更集 ${proposed.changesetId} - ${proposed.status} -> ${applied.status}`;
			})().catch((error: unknown) => {
				aiResult.textContent =
					error instanceof Error ? error.message : String(error);
			});
		});
		aiSection.append(aiInstruction, aiPropose, aiResult);
		resourcePanel.append(
			save,
			status,
			incoming,
			roster,
			presence,
			aiSection,
			commentsSection,
		);
		// History panel (arch 08): timeline + restore at a version.
		const historySection = document.createElement("section");
		historySection.dataset.testid = "history-panel";
		const historyList = document.createElement("ul");
		historyList.dataset.testid = "history-list";
		const historyStatus = document.createElement("p");
		historyStatus.dataset.testid = "history-status";
		const versionLabel = document.createElement("input");
		versionLabel.dataset.testid = "version-label";
		versionLabel.placeholder = "命名当前版本…";
		const versionAdd = document.createElement("button");
		versionAdd.type = "button";
		versionAdd.dataset.testid = "version-submit";
		versionAdd.textContent = "命名版本";
		const renderHistory = async (): Promise<void> => {
			try {
				const { DomClient } = await import("@dom/client-sdk");
				const result = await new DomClient().listHistory(resourceId);
				historyList.replaceChildren();
				for (const node of result.items) {
					const row = document.createElement("li");
					row.dataset.testid = "history-row";
					row.textContent = `${node.kind} v${node.seq}${
						node.label ? ` (${node.label})` : ""
					}`;
					if (node.kind === "NamedVersion") {
						row.dataset.testid = "named-version-row";
						row.textContent = `命名版本 ${node.label} (v${node.seq})`;
					}
					const restore = document.createElement("button");
					restore.type = "button";
					restore.dataset.testid = "history-restore";
					restore.textContent = "恢复";
					restore.addEventListener("click", (event) => {
						event.stopPropagation();
						void (async () => {
							try {
								const { DomClient } = await import("@dom/client-sdk");
								const done = await new DomClient().restoreVersion(
									resourceId,
									node.seq,
								);
								historyStatus.textContent = `已恢复到 v${done.newSeq}（${done.label}）`;
								await renderHistory();
							} catch (error) {
								historyStatus.textContent =
									error instanceof Error ? error.message : String(error);
							}
						})();
					});
					row.append(restore);
					historyList.append(row);
				}
			} catch {
				historyList.replaceChildren();
			}
		};
		versionAdd.addEventListener("click", (event) => {
			event.stopPropagation();
			void (async () => {
				try {
					const { DomClient } = await import("@dom/client-sdk");
					const result = await new DomClient().listHistory(resourceId);
					const latest = result.items[0];
					if (!latest) {
						historyStatus.textContent = "尚无版本可命名";
						return;
					}
					await new DomClient().createNamedVersion(
						resourceId,
						versionLabel.value,
						latest.seq,
					);
					historyStatus.textContent = `已命名（${versionLabel.value}）`;
					versionLabel.value = "";
					await renderHistory();
				} catch (error) {
					historyStatus.textContent =
						error instanceof Error ? error.message : String(error);
				}
			})();
		});
		void renderHistory();
		historySection.append(historyList, versionLabel, versionAdd, historyStatus);
		resourcePanel.append(historySection);
		app.append(resourcePanel);
	}

	const draft = document.createElement("textarea");
	draft.dataset.testid = "editor-draft-textarea";
	draft.value = readDraft();
	draft.addEventListener("input", writeDraftListener);
	// Live body CRDT + presence only make sense with an open resource; the
	// declarations are function-scoped and filled inside the resource branch.
	if (resourceId !== null && liveDocumentP && publishYjsImpl) {
		draft.addEventListener("input", () => {
			// presence + the yjs update share the 400ms debounce so both ride
			// the same settled relay window (peer subscription warm).
			if (idleLiveTimer) clearTimeout(idleLiveTimer);
			idleLiveTimer = setTimeout(() => publishPresence(false), 2000);
			void liveDocumentP?.then((doc) => {
				void import("@dom/yjs-runtime").then((m) =>
					m.setText(doc, draft.value),
				);
			});
			if (yjsLiveTimer) clearTimeout(yjsLiveTimer);
			yjsLiveTimer = setTimeout(() => {
				publishPresence(true);
				publishYjsImpl?.();
			}, 400);
		});
	}
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
