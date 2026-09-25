import { createTextDocument, type TextEditorSurface } from "@dom/editor-core";
import type { RealtimeConnectionState } from "@dom/realtime-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { client } from "../../shared/api/client";
import { resourceRuntime } from "../../shared/api/resource-runtime";
import {
	getResourceRealtimeClient,
	resetResourceRealtimeClient,
} from "../../shared/realtime";
import { ConsoleIcon } from "../../shared/ui/console-icons";
import { AiChangesetsPanel } from "../ai-changesets";
import { CommentsPanel } from "../comments";
import { HistoryPanel } from "../history";

type OpenedResource = Awaited<ReturnType<typeof resourceRuntime.openResource>>;
type DrawerTab = "comments" | "history" | "ai";

function realtimeStatusLabel(status: RealtimeConnectionState): string {
	if (status === "connected") return "协同已连接";
	if (status === "connecting") return "正在连接";
	if (status === "replaced") return "账号已在另一台设备登录";
	return "暂未连接";
}

function encodeBase64(bytes: Uint8Array): string {
	let binary = "";
	const chunkSize = 0x8000;
	for (let offset = 0; offset < bytes.length; offset += chunkSize) {
		binary += String.fromCharCode(
			...bytes.subarray(offset, offset + chunkSize),
		);
	}
	return btoa(binary);
}

function snapshotText(snapshot: unknown): string {
	if (typeof snapshot !== "object" || snapshot === null) return "";
	const value = (snapshot as { text?: unknown }).text;
	return typeof value === "string" ? value : "";
}

function EditorSessionDialog({ onLogin }: { onLogin(): void }) {
	return (
		<dialog
			open
			className="session-replaced-dialog"
			data-testid="session-replaced-dialog"
		>
			<h2>当前账号已在另一台设备登录，本设备已下线</h2>
			<p>本设备已下线。请重新登录以继续。</p>
			<button
				type="button"
				data-testid="session-replaced-relogin"
				onClick={onLogin}
			>
				重新登录
			</button>
		</dialog>
	);
}

export function EditorPage() {
	const navigate = useNavigate();
	const [params] = useSearchParams();
	const resourceId = params.get("resourceId") ?? params.get("resource");
	const [replaced, setReplaced] = useState(false);
	const [realtimeStatus, setRealtimeStatus] =
		useState<RealtimeConnectionState>("connecting");
	const account = useQuery({
		queryKey: ["account"],
		queryFn: () => client.me(),
	});

	useEffect(() => {
		if (!account.data?.accountId) return;
		const realtime = getResourceRealtimeClient();
		const unsubscribeState = realtime.onConnectionState(setRealtimeStatus);
		const unsubscribeReplacement = realtime.onSessionReplaced(() => {
			resetResourceRealtimeClient();
			setRealtimeStatus("replaced");
			setReplaced(true);
		});
		return () => {
			unsubscribeState();
			unsubscribeReplacement();
		};
	}, [account.data?.accountId]);

	const resource = useQuery({
		queryKey: ["resource", account.data?.accountId, resourceId],
		queryFn: () =>
			resourceRuntime.openResource(
				account.data?.accountId as string,
				resourceId as string,
			),
		enabled: !!account.data?.accountId && !!resourceId,
		retry: false,
	});

	useEffect(() => {
		if (account.isSuccess && account.data === null)
			navigate("/login", { replace: true });
	}, [account.data, account.isSuccess, navigate]);

	if (account.isLoading)
		return (
			<div className="app-stage">
				<p className="console-loading">正在验证会话…</p>
			</div>
		);
	if (account.data === null) return <Navigate to="/login" replace />;
	if (account.isError) {
		return (
			<div className="app-stage">
				<section className="editor-load-error" role="alert">
					<p data-testid="editor-session-error">
						服务暂时不可用，请检查网络后重试。
					</p>
					<button type="button" onClick={() => void account.refetch()}>
						重新加载
					</button>
				</section>
			</div>
		);
	}

	const accountId = account.data?.accountId;
	return (
		<div className="app-stage editor-stage" data-testid="editor-shell">
			{resourceId ? (
				resource.isLoading ? (
					<div className="editor-load-error">正在打开资源…</div>
				) : resource.isError || !resource.data ? (
					<div
						className="editor-load-error"
						role="alert"
						data-testid="resource-error"
					>
						<p>
							{resource.error instanceof Error
								? resource.error.message
								: "无法打开此资源。"}
						</p>
						<button type="button" onClick={() => void resource.refetch()}>
							重试
						</button>
					</div>
				) : accountId ? (
					<ResourceEditor
						key={resourceId}
						accountId={accountId}
						opened={resource.data}
						realtimeStatus={realtimeStatus}
						onBack={() => navigate("/workspace")}
					/>
				) : null
			) : (
				<EmptyEditor
					realtimeStatus={realtimeStatus}
					onBack={() => navigate("/workspace")}
				/>
			)}
			{replaced && <EditorSessionDialog onLogin={() => navigate("/login")} />}
		</div>
	);
}

function EmptyEditor({
	realtimeStatus,
	onBack,
}: {
	realtimeStatus: RealtimeConnectionState;
	onBack(): void;
}) {
	return (
		<div className="editor-shell">
			<header className="editor-topbar">
				<button
					type="button"
					className="btn-editor-back"
					data-testid="editor-back"
					onClick={onBack}
				>
					<ConsoleIcon name="arrowLeft" size={14} /> 返回管理台
				</button>
				<span
					className={`editor-realtime-status ${realtimeStatus}`}
					data-testid="realtime-status"
				>
					<span className="realtime-status-dot" aria-hidden="true" />
					{realtimeStatusLabel(realtimeStatus)}
				</span>
			</header>
			<main className="editor-canvas-container">
				<section className="editor-doc-paper">
					<p>请从工作区选择一个资源。</p>
				</section>
			</main>
		</div>
	);
}

function ResourceEditor({
	accountId,
	opened,
	realtimeStatus,
	onBack,
}: {
	accountId: string;
	opened: OpenedResource;
	realtimeStatus: RealtimeConnectionState;
	onBack(): void;
}) {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const cache = opened.resource;
	const resourceId = cache.resourceId;
	const [document] = useState(() => {
		const model = createTextDocument(opened.localUpdate ?? undefined);
		if (!opened.localUpdate) model.setText(snapshotText(cache.snapshot));
		model.flushLocalUpdates();
		return model;
	});
	const editorHost = useRef<HTMLDivElement>(null);
	const editorSurface = useRef<TextEditorSurface | null>(null);
	const persistTimer = useRef<number | null>(null);
	const [text, setText] = useState(document.getText());
	const [title, setTitle] = useState(cache.name);
	const [journalSeq, setJournalSeq] = useState(cache.journalSeq);
	const [saveMessage, setSaveMessage] = useState("");
	const [storageMessage, setStorageMessage] = useState("");
	const [roster, setRoster] = useState(0);
	const [tab, setTab] = useState<DrawerTab>("comments");
	const [drawerOpen, setDrawerOpen] = useState(
		() => !window.matchMedia("(max-width: 699px)").matches,
	);
	const [sourceMode, setSourceMode] = useState(false);
	const [trashPending, setTrashPending] = useState(false);
	const [renameError, setRenameError] = useState("");
	const [unboundDraft, setUnboundDraft] = useState("");

	const tree = useQuery({
		queryKey: ["project-tree", cache.projectId],
		queryFn: () => client.getProjectTree(cache.projectId),
	});
	const workspaces = useQuery({
		queryKey: ["workspaces"],
		queryFn: () => client.listWorkspaces(),
	});
	const projectList = useQuery({
		queryKey: ["projects", tree.data?.workspaceId],
		queryFn: () => client.listProjects(tree.data?.workspaceId as string),
		enabled: !!tree.data?.workspaceId,
	});
	const workspaceName = workspaces.data?.workspaces.find(
		(item) => item.workspaceId === tree.data?.workspaceId,
	)?.name;
	const projectName =
		projectList.data?.items.find((item) => item.projectId === cache.projectId)
			?.name ?? tree.data?.project.name;
	const folders = tree.data?.folders ?? [];
	const folderPath: Array<{ folderId: string; name: string }> = [];
	let parent = folders.find((folder) => folder.folderId === cache.folderId);
	while (parent) {
		folderPath.unshift({ folderId: parent.folderId, name: parent.name });
		parent = folders.find(
			(folder) => folder.folderId === parent?.parentFolderId,
		);
	}

	useEffect(() => {
		if (!editorHost.current) return;
		const surface = document.mountEditor(editorHost.current);
		editorSurface.current = surface;
		return () => {
			surface.destroy();
			editorSurface.current = null;
		};
	}, [document]);

	useEffect(() => {
		const unsubscribe = document.onTextChange((value) => {
			setText(value);
			const updates = document.flushLocalUpdates();
			const realtime = getResourceRealtimeClient();
			for (const update of updates) realtime.publishUpdate(resourceId, update);
			if (persistTimer.current !== null)
				window.clearTimeout(persistTimer.current);
			persistTimer.current = window.setTimeout(() => {
				void resourceRuntime
					.persistLocalState(
						accountId,
						resourceId,
						document.exportState(),
						cache,
					)
					.then(() => setStorageMessage("草稿已保存在本机。"))
					.catch((error: unknown) =>
						setStorageMessage(
							error instanceof Error ? error.message : "本地草稿保存失败。",
						),
					);
			}, 250);
		});
		return () => {
			unsubscribe();
			if (persistTimer.current !== null) {
				window.clearTimeout(persistTimer.current);
				persistTimer.current = null;
			}
		};
	}, [accountId, cache, document, resourceId]);

	useEffect(() => {
		const realtime = getResourceRealtimeClient();
		return realtime.subscribeResource(resourceId, {
			getStateVector: () => document.stateVector(),
			getLocalState: () => document.exportState(),
			onUpdate: (update) => document.applyRemoteUpdate(update),
			onPeers: setRoster,
			onStatus: (state) => {
				if (state === "denied")
					setSaveMessage("当前账号没有此资源的访问权限。");
			},
		});
	}, [document, resourceId]);

	useEffect(() => {
		setUnboundDraft(resourceRuntime.readUnboundRecoveryDraft());
	}, []);

	useEffect(() => () => document.destroy(), [document]);

	async function save() {
		try {
			const update = document.exportState();
			const result = await client.appendJournalOp(resourceId, {
				update: encodeBase64(update),
				expectedSeq: Math.max(1, journalSeq + 1),
				idempotencyKey: crypto.randomUUID(),
			});
			setJournalSeq(result.journalSeq);
			setSaveMessage("已保存");
		} catch (error) {
			setSaveMessage(
				error instanceof Error ? error.message : "保存失败，请重试。",
			);
		}
	}

	async function reloadContentFromServer() {
		const fresh = await client.openResource(resourceId);
		document.setText(snapshotText(fresh.snapshot));
		setJournalSeq(fresh.journalSeq);
		await resourceRuntime.persistLocalState(
			accountId,
			resourceId,
			document.exportState(),
			fresh,
		);
		await queryClient.invalidateQueries({
			queryKey: ["resource", accountId, resourceId],
		});
	}

	async function rename() {
		if (title.trim() === cache.name || !title.trim()) return;
		try {
			await client.renameResource(resourceId, {
				name: title.trim(),
				idempotencyKey: crypto.randomUUID(),
			});
			setRenameError("");
			await queryClient.invalidateQueries({ queryKey: ["resources"] });
		} catch (error) {
			setRenameError(error instanceof Error ? error.message : "重命名失败。");
		}
	}

	async function trash() {
		setTrashPending(true);
		try {
			await client.trashResource(resourceId, {
				idempotencyKey: crypto.randomUUID(),
			});
			await queryClient.invalidateQueries({ queryKey: ["resources"] });
			navigate(
				`/workspace?workspaceId=${encodeURIComponent(tree.data?.workspaceId ?? "")}&view=trash`,
			);
		} catch (error) {
			setSaveMessage(
				error instanceof Error ? error.message : "移入回收站失败。",
			);
			setTrashPending(false);
		}
	}

	function recoverUnboundDraft() {
		document.setText(unboundDraft);
		setUnboundDraft("");
		setSaveMessage("未关联草稿已复制到当前资源；请检查内容后手动保存。");
	}

	function exportUnboundDraft() {
		const blob = new Blob([unboundDraft], { type: "text/plain;charset=utf-8" });
		const url = URL.createObjectURL(blob);
		const link = window.document.createElement("a");
		link.href = url;
		link.download = "dom-draft.txt";
		link.click();
		URL.revokeObjectURL(url);
	}

	return (
		<div className="editor-shell">
			<header className="editor-topbar">
				<div className="editor-nav-left">
					<button
						type="button"
						className="btn-editor-back"
						data-testid="editor-back"
						onClick={onBack}
					>
						<ConsoleIcon name="arrowLeft" size={14} /> 返回管理台
					</button>
					<nav
						className="breadcrumb-trail editor-breadcrumb"
						aria-label="编辑器位置"
						data-testid="editor-breadcrumb"
					>
						<button
							type="button"
							className="breadcrumb-item"
							onClick={() =>
								navigate(
									`/workspace?workspaceId=${encodeURIComponent(tree.data?.workspaceId ?? "")}`,
								)
							}
						>
							{workspaceName ?? "工作区"}
						</button>
						<span className="breadcrumb-sep">/</span>
						<button
							type="button"
							className="breadcrumb-item"
							onClick={() =>
								navigate(
									`/workspace?workspaceId=${encodeURIComponent(tree.data?.workspaceId ?? "")}&projectId=${encodeURIComponent(cache.projectId)}`,
								)
							}
						>
							{projectName ?? "项目"}
						</button>
						{folderPath.map((folder) => (
							<span className="editor-crumb-folder" key={folder.folderId}>
								<span className="breadcrumb-sep">/</span>
								<button
									type="button"
									className="breadcrumb-item"
									onClick={() =>
										navigate(
											`/workspace?workspaceId=${encodeURIComponent(tree.data?.workspaceId ?? "")}&projectId=${encodeURIComponent(cache.projectId)}&folderId=${encodeURIComponent(folder.folderId)}`,
										)
									}
								>
									{folder.name}
								</button>
							</span>
						))}
						<span className="breadcrumb-sep">/</span>
						<span className="breadcrumb-item current">{title}</span>
					</nav>
				</div>
				<div className="topbar-right">
					<span
						className="editor-roster-badge"
						data-testid="editor-roster-badge"
						hidden={roster < 1}
					>
						<span className="roster-dot" />
						<span data-testid="editor-roster">{roster} 人在线</span>
					</span>
					<span
						className={`editor-realtime-status ${realtimeStatus}`}
						data-testid="realtime-status"
						data-state={realtimeStatus}
					>
						<span className="realtime-status-dot" aria-hidden="true" />
						{realtimeStatusLabel(realtimeStatus)}
					</span>
					<button
						type="button"
						className="icon-btn-quiet"
						data-testid="editor-trash"
						aria-label="移入回收站"
						title="移入回收站"
						disabled={trashPending}
						onClick={() => void trash()}
					>
						<ConsoleIcon name="trash" />
					</button>
					<button
						type="button"
						className="icon-btn-quiet"
						data-testid="editor-panel-toggle"
						aria-label="展开或收起辅助面板"
						aria-expanded={drawerOpen}
						title={drawerOpen ? "收起辅助面板" : "展开辅助面板"}
						onClick={() => setDrawerOpen((value) => !value)}
					>
						<ConsoleIcon name="panel" size={18} />
					</button>
				</div>
			</header>
			<div className="editor-body">
				<main className="editor-canvas-container">
					<article className="editor-doc-paper">
						<div className="doc-collab-hint">
							<span data-testid="editor-presence" data-state={realtimeStatus}>
								<span
									className={`realtime-status-dot ${realtimeStatus}`}
									aria-hidden="true"
								/>
								{realtimeStatus === "connected"
									? "正在协同编辑"
									: realtimeStatusLabel(realtimeStatus)}
							</span>
							<span
								className="journal-badge-editor"
								data-testid="editor-journal-seq"
							>
								记录 #{journalSeq}
							</span>
						</div>
						<input
							className="doc-title-input"
							value={title}
							onChange={(event) => setTitle(event.target.value)}
							onBlur={() => void rename()}
							aria-label="资源名称"
							data-testid="resource-name-input"
						/>
						{renameError && (
							<p className="feature-error" role="alert">
								{renameError}
							</p>
						)}
						<div
							className="editor-toolbar"
							role="toolbar"
							aria-label="编辑工具"
						>
							<fieldset className="editor-toolbar-group">
								<legend className="sr-only">文字格式</legend>
								<button
									type="button"
									title="加粗"
									onClick={() => editorSurface.current?.toggleMark("strong")}
									aria-label="加粗"
								>
									<strong>B</strong>
								</button>
								<button
									type="button"
									title="斜体"
									onClick={() => editorSurface.current?.toggleMark("em")}
									aria-label="斜体"
								>
									<i>I</i>
								</button>
								<button
									type="button"
									title="代码"
									onClick={() => editorSurface.current?.toggleMark("code")}
									aria-label="代码"
								>
									<code>&lt;/&gt;</code>
								</button>
							</fieldset>
							<span className="editor-toolbar-divider" aria-hidden="true" />
							<button
								type="button"
								data-testid="editor-rich-toggle"
								onClick={() => setSourceMode((value) => !value)}
							>
								{sourceMode ? "富文本" : "源码"}
							</button>
							<button
								type="button"
								className="primary"
								data-testid="editor-save"
								onClick={() => void save()}
							>
								保存
							</button>
						</div>
						<div className="editor-source-wrap" hidden={!sourceMode}>
							<textarea
								value={text}
								onChange={(event) => document.setText(event.target.value)}
								aria-label="文档源码"
								data-testid="editor-draft-textarea"
							/>
						</div>
						<div
							className="editor-rich-body"
							data-testid="editor-rich-body"
							hidden={sourceMode}
							ref={editorHost}
						/>
						<p className="editor-status-line" data-testid="editor-save-status">
							{saveMessage}
							{saveMessage === "已保存" && (
								<span className="sr-only" aria-hidden="true">
									journalSeq={journalSeq}
								</span>
							)}
						</p>
						<p
							className="editor-status-line"
							data-testid="editor-offline-status"
						>
							{storageMessage ||
								(opened.source === "offline-cache" ? "离线内容" : "")}
						</p>
						{opened.source === "offline-cache" && (
							<p className="feature-muted">
								当前显示此账号保存在本地的离线内容。
							</p>
						)}
						{unboundDraft && (
							<section
								className="draft-recovery-banner"
								data-testid="draft-recovery-banner"
							>
								<strong>检测到一个未关联资源的旧草稿</strong>
								<p>
									系统不会猜测它属于哪份文档。选择复制到当前资源后，请检查并手动保存。
								</p>
								<pre data-testid="draft-recovery-content">{unboundDraft}</pre>
								<div className="editor-toolbar">
									<button type="button" onClick={recoverUnboundDraft}>
										复制到当前资源
									</button>
									<button
										type="button"
										data-testid="draft-export-button"
										onClick={exportUnboundDraft}
									>
										导出旧草稿
									</button>
								</div>
							</section>
						)}
					</article>
				</main>
				<button
					type="button"
					className={`editor-drawer-backdrop ${drawerOpen ? "show" : ""}`}
					data-testid="editor-drawer-backdrop"
					aria-label="关闭辅助面板"
					onClick={() => setDrawerOpen(false)}
				/>
				<aside
					className={`editor-drawer ${drawerOpen ? "mobile-open" : "collapsed"}`}
					data-testid="editor-drawer"
				>
					<div className="drawer-tabs-header">
						{(["comments", "history", "ai"] as const).map((name) => (
							<button
								type="button"
								key={name}
								className={`drawer-tab-btn ${tab === name ? "active" : ""}`}
								data-testid={`editor-panel-tab-${name}`}
								onClick={() => {
									setTab(name);
									setDrawerOpen(true);
								}}
							>
								<ConsoleIcon
									name={
										name === "comments"
											? "comments"
											: name === "history"
												? "history"
												: "sparkle"
									}
									size={14}
								/>
								<span>
									{name === "comments"
										? "评论"
										: name === "history"
											? "历史"
											: "AI 提案"}
								</span>
							</button>
						))}
					</div>
					<div className="drawer-tab-pane active" hidden={tab !== "comments"}>
						<CommentsPanel
							resourceId={resourceId}
							workspaceId={tree.data?.workspaceId}
							onJumpToAnchor={(quote) =>
								editorSurface.current?.selectText(quote)
							}
						/>
					</div>
					<div className="drawer-tab-pane active" hidden={tab !== "history"}>
						<HistoryPanel
							resourceId={resourceId}
							journalSeq={journalSeq}
							onRestored={reloadContentFromServer}
						/>
					</div>
					<div className="drawer-tab-pane active" hidden={tab !== "ai"}>
						<AiChangesetsPanel
							resourceId={resourceId}
							onApplied={reloadContentFromServer}
						/>
					</div>
				</aside>
			</div>
		</div>
	);
}
