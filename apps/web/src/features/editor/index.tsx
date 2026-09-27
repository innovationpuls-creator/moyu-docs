import { DomApiError } from "@dom/client-sdk";
import {
	type AssetReference,
	createTextDocument,
	type NewAssetReference,
	type TextEditorSurface,
} from "@dom/editor-core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { client } from "../../shared/api/client";
import { resourceRuntime } from "../../shared/api/resource-runtime";
import {
	getResourceRealtimeClient,
	resetResourceRealtimeClient,
} from "../../shared/realtime";
import { ConsoleIcon } from "../../shared/ui/console-icons";
import { AiChangesetsPanel } from "../ai-changesets";
import { AssetsPanel } from "../assets";
import { CommentsPanel } from "../comments";
import { HistoryPanel } from "../history";
import { ImportExportPanel } from "../importexport";
import { SharePanel } from "../shares";

type OpenedResource = Awaited<ReturnType<typeof resourceRuntime.openResource>>;
type LocalResourceSnapshot = Awaited<
	ReturnType<typeof resourceRuntime.persistLocalState>
>;
type PendingJournalSnapshot = {
	snapshot: LocalResourceSnapshot;
	idempotencyKey: string;
	coveredSnapshots: LocalResourceSnapshot[];
	changeGeneration: number;
};
type RemoteCursor = Parameters<
	TextEditorSurface["setRemoteCursors"]
>[0][number];
type DrawerTab =
	| "comments"
	| "history"
	| "ai"
	| "assets"
	| "share"
	| "importexport";

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

function isPermanentSyncRejection(error: unknown): error is DomApiError {
	return error instanceof DomApiError && !error.retryable;
}

function syncRejectionMessage(error: DomApiError): string {
	switch (error.errorCode) {
		case "SESSION_EXPIRED":
		case "SESSION_REPLACED":
		case "SESSION_NOT_AUTHORIZED":
			return "登录状态已失效，请重新登录后重试同步。";
		case "RESOURCE_PERMISSION_DENIED":
			return "你没有编辑这份文档的权限。恢复权限后可重试同步。";
		case "RESOURCE_NOT_FOUND":
			return "这份文档目前无法访问。确认它仍存在且你有权查看后，可重试同步。";
		default:
			return "同步失败，服务器未接收这次修改。";
	}
}

type InlineAssetMetadata = Awaited<
	ReturnType<typeof client.listResourceAssets>
>["assets"];

function renderInlineAsset(
	container: HTMLElement,
	reference: AssetReference,
	getAssetMetadata: () => Promise<InlineAssetMetadata>,
): () => void {
	const label =
		reference.label || (reference.kind === "image" ? "图片" : "附件");
	let disposed = false;
	if (reference.kind === "image") {
		const image = container as HTMLImageElement;
		image.alt = label;
		image.draggable = true;
		image.src = client.assetUrl(reference.assetId);
		return () => {};
	} else {
		container.textContent = label;
		void getAssetMetadata()
			.then(async (assets) => {
				const asset = assets.find((item) => item.assetId === reference.assetId);
				const mime = asset?.mime?.split(";", 1)[0]?.trim().toLowerCase();
				if (!asset || mime !== "text/plain" || asset.sizeBytes > 64 * 1024)
					return;
				const blob = await client.downloadAsset(reference.assetId);
				if (disposed) return;
				container.style.whiteSpace = "pre-wrap";
				container.textContent = await blob.text();
			})
			.catch(() => {
				if (!disposed) container.textContent = `${label}（预览不可用）`;
			});
	}
	return () => {
		disposed = true;
	};
}

function createInlineAssetRenderer(resourceId: string) {
	let metadataPromise: Promise<InlineAssetMetadata> | null = null;
	const getAssetMetadata = () => {
		metadataPromise ??= client
			.listResourceAssets(resourceId)
			.then(({ assets }) => assets);
		return metadataPromise;
	};
	return {
		render: (container: HTMLElement, reference: AssetReference) =>
			renderInlineAsset(container, reference, getAssetMetadata),
		invalidateMetadata: () => {
			metadataPromise = null;
		},
	};
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
	const sessionRevokedRef = useRef(false);
	const authenticatedThisMount = useRef(false);
	const [realtimeStatus, setRealtimeStatus] = useState("connecting");
	const [browserOnline, setBrowserOnline] = useState(() => navigator.onLine);
	const [cachedAccountId] = useState(() =>
		resourceRuntime.getCachedAccountId(),
	);
	const account = useQuery({
		queryKey: ["account"],
		queryFn: async () => {
			try {
				const current = await client.meForSessionRecovery();
				if (current) authenticatedThisMount.current = true;
				return current;
			} catch (error) {
				if (
					error instanceof DomApiError &&
					error.errorCode === "SESSION_REPLACED" &&
					!authenticatedThisMount.current
				) {
					return null;
				}
				throw error;
			}
		},
		retry: (failureCount, error) =>
			!(
				error instanceof DomApiError && error.errorCode === "SESSION_REPLACED"
			) && failureCount < 2,
	});
	const sessionReplacedByAuth =
		authenticatedThisMount.current &&
		account.error instanceof DomApiError &&
		account.error.errorCode === "SESSION_REPLACED";
	const sessionReplacementDetected = replaced || sessionReplacedByAuth;
	const localAccountId = cachedAccountId ?? account.data?.accountId;
	const serverAuthenticated =
		!!account.data?.accountId && !account.isError && browserOnline;
	const offlineIdentityAvailable =
		!serverAuthenticated &&
		!!localAccountId &&
		(!browserOnline ||
			account.error instanceof TypeError ||
			sessionReplacedByAuth ||
			replaced);
	const accountId =
		account.data?.accountId ??
		(offlineIdentityAvailable ? localAccountId : undefined);

	useEffect(() => {
		const goOnline = () => {
			setBrowserOnline(true);
			void account.refetch();
		};
		const goOffline = () => setBrowserOnline(false);
		window.addEventListener("online", goOnline);
		window.addEventListener("offline", goOffline);
		return () => {
			window.removeEventListener("online", goOnline);
			window.removeEventListener("offline", goOffline);
		};
	}, [account.refetch]);

	useEffect(() => {
		if (!account.data?.accountId) return;
		const realtime = getResourceRealtimeClient();
		const unsubscribeState = realtime.onConnectionState((state) => {
			setRealtimeStatus(state === "replaced" ? "closed:4001" : state);
		});
		const unsubscribeReplacement = realtime.onSessionReplaced(() => {
			sessionRevokedRef.current = true;
			resetResourceRealtimeClient();
			setRealtimeStatus("closed:4001");
			setReplaced(true);
		});
		return () => {
			unsubscribeState();
			unsubscribeReplacement();
		};
	}, [account.data?.accountId]);

	const resource = useQuery({
		queryKey: ["resource", accountId, resourceId],
		queryFn: () =>
			resourceRuntime.openResource(accountId as string, resourceId as string),
		enabled: !!accountId && !!resourceId,
		retry: false,
	});

	useEffect(() => {
		if (account.isSuccess && account.data === null)
			navigate("/login", { replace: true });
	}, [account.data, account.isSuccess, navigate]);

	if (account.isLoading && !offlineIdentityAvailable)
		return (
			<div className="app-stage">
				<p className="console-loading">正在验证会话…</p>
			</div>
		);
	if (account.data === null) return <Navigate to="/login" replace />;
	if (account.isError && !offlineIdentityAvailable) {
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
						serverAuthenticated={serverAuthenticated}
						sessionReplaced={sessionReplacementDetected}
						sessionRevokedRef={sessionRevokedRef}
						onBack={() => navigate("/workspace")}
					/>
				) : null
			) : (
				<EmptyEditor
					realtimeStatus={realtimeStatus}
					onBack={() => navigate("/workspace")}
				/>
			)}
			{sessionReplacementDetected && (
				<EditorSessionDialog onLogin={() => navigate("/login")} />
			)}
		</div>
	);
}

function EmptyEditor({
	realtimeStatus,
	onBack,
}: {
	realtimeStatus: string;
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
					返回管理台
				</button>
				<span className="editor-status-line" data-testid="realtime-status">
					{realtimeStatus}
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
	serverAuthenticated,
	sessionReplaced,
	sessionRevokedRef,
	onBack,
}: {
	accountId: string;
	opened: OpenedResource;
	realtimeStatus: string;
	serverAuthenticated: boolean;
	sessionReplaced: boolean;
	sessionRevokedRef: { current: boolean };
	onBack(): void;
}) {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const cache = opened.resource;
	const resourceId = cache.resourceId;
	const localRecoverySnapshots = opened.localSnapshots.filter(
		(snapshot) => snapshot.revision > snapshot.durableRevision,
	);
	const useLocalState =
		opened.source === "offline-cache" ||
		localRecoverySnapshots.length > 0 ||
		opened.localSnapshots.length > 0 ||
		(opened.localSnapshots.length === 0 && opened.localUpdate !== null);
	const [document] = useState(() => {
		if (useLocalState) {
			const firstLocalUpdate =
				opened.localSnapshots[0]?.update ?? opened.localUpdate ?? undefined;
			const model = createTextDocument(firstLocalUpdate);
			if (!firstLocalUpdate) model.setText(snapshotText(cache.snapshot));
			for (const snapshot of opened.localSnapshots.slice(1)) {
				model.applyRemoteUpdate(snapshot.update);
			}
			model.flushLocalUpdates();
			return model;
		}
		const model = createTextDocument();
		model.setText(snapshotText(cache.snapshot));
		model.flushLocalUpdates();
		return model;
	});
	const editorHost = useRef<HTMLDivElement>(null);
	const editorSurface = useRef<TextEditorSurface | null>(null);
	const inlineAssetRenderer = useRef<ReturnType<
		typeof createInlineAssetRenderer
	> | null>(null);
	const remoteCursors = useRef(new Map<string, RemoteCursor>());
	const persistTimer = useRef<number | null>(null);
	const journalRetryTimer = useRef<number | null>(null);
	const journalSeqRef = useRef(cache.journalSeq);
	const latestSnapshotRef = useRef<LocalResourceSnapshot | null>(null);
	const persistedChangeGenerationRef = useRef(0);
	const coveredSnapshotsRef = useRef(localRecoverySnapshots);
	const hasUnconfirmedLocalChangesRef = useRef(
		localRecoverySnapshots.length > 0,
	);
	const documentChangeGenerationRef = useRef(0);
	const serverAuthenticatedRef = useRef(
		serverAuthenticated && !sessionReplaced && !sessionRevokedRef.current,
	);
	serverAuthenticatedRef.current =
		serverAuthenticated && !sessionReplaced && !sessionRevokedRef.current;
	const pendingJournalRef = useRef<PendingJournalSnapshot | null>(null);
	const journalInFlight = useRef(false);
	const runPendingJournal = useRef<() => void>(() => {});
	const [text, setText] = useState(document.getText());
	const [title, setTitle] = useState(cache.name);
	const [journalSeq, setJournalSeq] = useState(cache.journalSeq);
	const [saveMessage, setSaveMessage] = useState("");
	const [storageMessage, setStorageMessage] = useState("");
	const [syncRejected, setSyncRejected] = useState(false);
	const syncRejectedRef = useRef(false);
	const [leavingEditor, setLeavingEditor] = useState(false);
	const [localStatus, setLocalStatus] = useState(
		opened.source === "offline-cache"
			? "离线编辑中；本地修改将在重新验证会话后同步。"
			: "",
	);
	const [roster, setRoster] = useState(0);
	const [tab, setTab] = useState<DrawerTab>("comments");
	const [drawerOpen, setDrawerOpen] = useState(
		() => !window.matchMedia("(max-width: 699px)").matches,
	);
	const [sourceMode, setSourceMode] = useState(false);
	const [trashPending, setTrashPending] = useState(false);
	const [renameError, setRenameError] = useState("");
	const [unboundDraft, setUnboundDraft] = useState("");
	const canQueueJournal = useCallback(
		() => serverAuthenticatedRef.current && !sessionRevokedRef.current,
		[sessionRevokedRef],
	);
	const canPublishRealtime = useCallback(
		() => canQueueJournal() && !syncRejectedRef.current,
		[canQueueJournal],
	);
	const isSyncPaused = useCallback(() => syncRejectedRef.current, []);

	const pauseSync = useCallback((message: string) => {
		syncRejectedRef.current = true;
		setSyncRejected(true);
		setSaveMessage(message);
		setLocalStatus("修改已保存在这台设备，尚未同步到服务器。");
		if (journalRetryTimer.current !== null) {
			window.clearTimeout(journalRetryTimer.current);
			journalRetryTimer.current = null;
		}
	}, []);

	runPendingJournal.current = () => {
		if (
			!serverAuthenticatedRef.current ||
			sessionRevokedRef.current ||
			syncRejectedRef.current ||
			!navigator.onLine ||
			journalInFlight.current ||
			!pendingJournalRef.current
		) {
			return;
		}
		const attempt = pendingJournalRef.current;
		pendingJournalRef.current = null;
		journalInFlight.current = true;
		void (async () => {
			try {
				const result = await client.appendJournalOp(resourceId, {
					update: encodeBase64(attempt.snapshot.update),
					expectedSeq: Math.max(1, journalSeqRef.current + 1),
					idempotencyKey: attempt.idempotencyKey,
				});
				const receipt = result as typeof result & {
					acceptedWatermark?: number;
					durableWatermark?: number;
				};
				if (
					!Number.isSafeInteger(receipt.journalSeq) ||
					!Number.isSafeInteger(receipt.acceptedWatermark) ||
					!Number.isSafeInteger(receipt.durableWatermark) ||
					receipt.acceptedWatermark === undefined ||
					receipt.durableWatermark === undefined ||
					receipt.acceptedWatermark < receipt.journalSeq ||
					receipt.durableWatermark < receipt.journalSeq
				) {
					throw new Error(
						"服务器未返回可确认的持久化回执；本地修改仍在等待同步。",
					);
				}
				journalSeqRef.current = Math.max(
					journalSeqRef.current,
					receipt.journalSeq,
				);
				setJournalSeq(journalSeqRef.current);
				setSaveMessage("");
				const confirmedSnapshots = [
					attempt.snapshot,
					...attempt.coveredSnapshots,
				];
				for (const snapshot of confirmedSnapshots) {
					await resourceRuntime.recordConfirmedRevisions(
						accountId,
						resourceId,
						snapshot.replicaId,
						{
							acceptedRevision: snapshot.revision,
							durableRevision: snapshot.revision,
						},
					);
				}
				coveredSnapshotsRef.current = [];
				const latestSnapshot = latestSnapshotRef.current;
				const hasNewerLocalSnapshot =
					documentChangeGenerationRef.current > attempt.changeGeneration ||
					(latestSnapshot?.revision ?? attempt.snapshot.revision) >
						attempt.snapshot.revision ||
					pendingJournalRef.current !== null;
				hasUnconfirmedLocalChangesRef.current = hasNewerLocalSnapshot;
				if (!hasNewerLocalSnapshot && latestSnapshot) {
					latestSnapshotRef.current = {
						...latestSnapshot,
						acceptedRevision: Math.max(
							latestSnapshot.acceptedRevision,
							latestSnapshot.revision,
						),
						durableRevision: Math.max(
							latestSnapshot.durableRevision,
							latestSnapshot.revision,
						),
					};
				}
				setLocalStatus(
					hasNewerLocalSnapshot
						? "服务器已确认此版本；较新的本地修改仍在同步。"
						: "服务器已确认本地更改持久保存。",
				);
			} catch (error) {
				if (
					error instanceof DomApiError &&
					error.errorCode === "RESOURCE_JOURNAL_SEQUENCE_CONFLICT"
				) {
					let refreshed = false;
					try {
						const latest = await client.openResource(resourceId);
						// This endpoint returns checkpoint metadata, not the durable Yjs
						// journal tail. The realtime state-vector stream owns body merge.
						journalSeqRef.current = latest.journalSeq;
						setJournalSeq(latest.journalSeq);
						setSaveMessage("");
						refreshed = true;
					} catch {
						setSaveMessage(
							"未能重新读取服务器序号；本地 Yjs 修改仍保留，稍后重试。",
						);
					}
					const newer = pendingJournalRef.current;
					const retrySnapshot =
						newer && newer.snapshot.revision > attempt.snapshot.revision
							? newer.snapshot
							: attempt.snapshot;
					pendingJournalRef.current = {
						snapshot: retrySnapshot,
						idempotencyKey: crypto.randomUUID(),
						coveredSnapshots:
							newer?.coveredSnapshots ?? attempt.coveredSnapshots,
						changeGeneration:
							newer?.changeGeneration ?? attempt.changeGeneration,
					};
					hasUnconfirmedLocalChangesRef.current = true;
					setLocalStatus(
						`检测到并发写入；本地修改已保留，正在重试提交。此回执不确认远端正文是否已合并（协同连接：${realtimeStatus}）。`,
					);
					if (
						navigator.onLine &&
						serverAuthenticatedRef.current &&
						!sessionRevokedRef.current &&
						!syncRejectedRef.current
					) {
						journalRetryTimer.current = window.setTimeout(
							() => {
								journalRetryTimer.current = null;
								runPendingJournal.current();
							},
							refreshed ? 100 : 2000,
						);
					}
					return;
				}
				if (
					!pendingJournalRef.current ||
					pendingJournalRef.current.snapshot.revision <
						attempt.snapshot.revision
				) {
					pendingJournalRef.current = attempt;
				}
				hasUnconfirmedLocalChangesRef.current = true;
				if (isPermanentSyncRejection(error)) {
					pauseSync(syncRejectionMessage(error));
					return;
				}
				if (sessionRevokedRef.current) {
					setLocalStatus(
						"会话已被替换；本地 Yjs 修改已保留，重新登录并验证权限后才能同步。",
					);
					return;
				}
				setSaveMessage(
					error instanceof Error ? error.message : "后台同步失败。",
				);
				setLocalStatus(
					navigator.onLine
						? "本地修改已保存，等待服务器确认。"
						: "当前离线；本地修改已保存，等待重新连接。",
				);
				if (journalRetryTimer.current !== null)
					window.clearTimeout(journalRetryTimer.current);
				if (
					navigator.onLine &&
					serverAuthenticatedRef.current &&
					!sessionRevokedRef.current &&
					!syncRejectedRef.current
				) {
					journalRetryTimer.current = window.setTimeout(() => {
						journalRetryTimer.current = null;
						runPendingJournal.current();
					}, 2000);
				}
			} finally {
				journalInFlight.current = false;
				if (
					pendingJournalRef.current &&
					pendingJournalRef.current.snapshot.revision >
						attempt.snapshot.revision
				) {
					runPendingJournal.current();
				}
			}
		})();
	};

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
		if (!sessionReplaced) return;
		sessionRevokedRef.current = true;
		syncRejectedRef.current = true;
		setSyncRejected(true);
		setSaveMessage("会话已被另一台设备替换；同步已暂停。");
		setLocalStatus("本地 Yjs 修改已保留；重新登录并验证资源权限后才能同步。");
		if (journalRetryTimer.current !== null) {
			window.clearTimeout(journalRetryTimer.current);
			journalRetryTimer.current = null;
		}
	}, [sessionReplaced, sessionRevokedRef]);

	useEffect(() => {
		if (!editorHost.current) return;
		const assetRenderer = createInlineAssetRenderer(resourceId);
		inlineAssetRenderer.current = assetRenderer;
		const surface = document.mountEditor(editorHost.current, {
			renderAsset: assetRenderer.render,
		});
		editorSurface.current = surface;
		return () => {
			surface.destroy();
			editorSurface.current = null;
			inlineAssetRenderer.current = null;
		};
	}, [document, resourceId]);

	useEffect(() => {
		const unsubscribe = document.onTextChange((value) => {
			documentChangeGenerationRef.current += 1;
			hasUnconfirmedLocalChangesRef.current = true;
			setText(value);
			const updates = document.flushLocalUpdates();
			if (canPublishRealtime()) {
				const realtime = getResourceRealtimeClient();
				for (const update of updates)
					realtime.publishUpdate(resourceId, update);
			}
			if (persistTimer.current !== null)
				window.clearTimeout(persistTimer.current);
			persistTimer.current = window.setTimeout(() => {
				persistTimer.current = null;
				const savedGeneration = documentChangeGenerationRef.current;
				void resourceRuntime
					.persistLocalState(
						accountId,
						resourceId,
						document.exportState(),
						cache,
					)
					.then((snapshot) => {
						latestSnapshotRef.current = snapshot;
						persistedChangeGenerationRef.current = Math.max(
							persistedChangeGenerationRef.current,
							savedGeneration,
						);
						hasUnconfirmedLocalChangesRef.current =
							snapshot.revision > snapshot.durableRevision;
						setStorageMessage("已保存在此设备。 ");
						if (canQueueJournal()) {
							pendingJournalRef.current = {
								snapshot,
								idempotencyKey: crypto.randomUUID(),
								coveredSnapshots: coveredSnapshotsRef.current,
								changeGeneration: documentChangeGenerationRef.current,
							};
							if (isSyncPaused()) {
								setLocalStatus("修改已保存在这台设备，尚未同步到服务器。");
							} else {
								setLocalStatus("本地修改已保存，正在同步到服务器…");
								runPendingJournal.current();
							}
						} else {
							setLocalStatus(
								"本地修改已保存；离线内容将在重新验证会话后同步。",
							);
						}
					})
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
	}, [
		accountId,
		cache,
		document,
		resourceId,
		canPublishRealtime,
		canQueueJournal,
		isSyncPaused,
	]);

	useEffect(() => {
		if (!serverAuthenticated || sessionReplaced || syncRejected) {
			setRoster(0);
			return;
		}
		const realtime = getResourceRealtimeClient();
		const surface = editorSurface.current;
		const unsubscribe = realtime.subscribeResource(resourceId, {
			getStateVector: () => document.stateVector(),
			getLocalState: () => document.exportState(),
			onUpdate: (update) => document.applyRemoteUpdate(update),
			onPeers: setRoster,
			onAwareness: (event) => {
				if (event.kind === "remove") {
					remoteCursors.current.delete(event.participantId);
				} else if (event.state.cursor === null) {
					remoteCursors.current.delete(event.participant.participantId);
				} else {
					remoteCursors.current.set(event.participant.participantId, {
						...event.participant,
						...event.state.cursor,
						text: document.getText(),
					});
				}
				surface?.setRemoteCursors([...remoteCursors.current.values()]);
			},
			onStatus: (state) => {
				if (state === "denied") {
					pauseSync("当前无法同步这份文档。请重新登录或检查编辑权限后重试。");
				}
			},
		});
		const unsubscribeSelection = surface?.onSelectionChange((cursor) => {
			if (canPublishRealtime())
				realtime.publishAwareness(resourceId, { cursor });
		});
		return () => {
			unsubscribeSelection?.();
			if (canPublishRealtime()) {
				realtime.publishAwareness(resourceId, { cursor: null });
			}
			remoteCursors.current.clear();
			unsubscribe();
		};
	}, [
		document,
		resourceId,
		serverAuthenticated,
		sessionReplaced,
		syncRejected,
		pauseSync,
		canPublishRealtime,
	]);

	useEffect(() => {
		if (
			!serverAuthenticated ||
			sessionReplaced ||
			syncRejected ||
			!hasUnconfirmedLocalChangesRef.current
		)
			return;
		if (pendingJournalRef.current) {
			runPendingJournal.current();
			return;
		}
		if (persistTimer.current !== null) {
			window.clearTimeout(persistTimer.current);
			persistTimer.current = null;
		}
		void resourceRuntime
			.persistLocalState(accountId, resourceId, document.exportState(), cache)
			.then((snapshot) => {
				latestSnapshotRef.current = snapshot;
				persistedChangeGenerationRef.current =
					documentChangeGenerationRef.current;
				hasUnconfirmedLocalChangesRef.current =
					snapshot.revision > snapshot.durableRevision;
				pendingJournalRef.current = {
					snapshot,
					idempotencyKey: crypto.randomUUID(),
					coveredSnapshots: coveredSnapshotsRef.current,
					changeGeneration: documentChangeGenerationRef.current,
				};
				setLocalStatus("正在恢复本地修改并提交到服务器…");
				runPendingJournal.current();
			})
			.catch(() =>
				setLocalStatus("本地恢复内容已保留，但暂时无法再次写入缓存。"),
			);
	}, [
		accountId,
		cache,
		document,
		resourceId,
		serverAuthenticated,
		sessionReplaced,
		syncRejected,
	]);

	useEffect(() => {
		setUnboundDraft(resourceRuntime.readUnboundRecoveryDraft());
	}, []);

	useEffect(() => () => document.destroy(), [document]);

	async function reloadContentFromServer() {
		const fresh = await client.openResource(resourceId);
		document.setText(snapshotText(fresh.snapshot));
		journalSeqRef.current = fresh.journalSeq;
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
		setSaveMessage("未关联草稿已复制到当前资源，请检查复制的内容。");
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

	function exportLocalYjsDraft() {
		const body = JSON.stringify(
			{
				format: "dom-yjs-update-base64-v1",
				resourceId,
				exportedAt: new Date().toISOString(),
				updateBase64: encodeBase64(document.exportState()),
			},
			null,
			2,
		);
		const blob = new Blob([body], { type: "application/json;charset=utf-8" });
		const url = URL.createObjectURL(blob);
		const link = window.document.createElement("a");
		link.href = url;
		link.download = `dom-resource-${resourceId}-local-draft.json`;
		link.click();
		URL.revokeObjectURL(url);
	}

	async function retryRejectedSync() {
		if (sessionRevokedRef.current || sessionReplaced) {
			setSaveMessage("请重新登录并验证资源权限后再同步本地修改。");
			return;
		}
		if (!serverAuthenticatedRef.current || !navigator.onLine) {
			setSaveMessage("请联网并重新验证会话后再同步本地修改。");
			return;
		}
		syncRejectedRef.current = false;
		setSyncRejected(false);
		setSaveMessage("");
		if (!pendingJournalRef.current && hasUnconfirmedLocalChangesRef.current) {
			if (persistTimer.current !== null) {
				window.clearTimeout(persistTimer.current);
				persistTimer.current = null;
			}
			try {
				const changeGeneration = documentChangeGenerationRef.current;
				const snapshot = await resourceRuntime.persistLocalState(
					accountId,
					resourceId,
					document.exportState(),
					cache,
				);
				latestSnapshotRef.current = snapshot;
				persistedChangeGenerationRef.current = changeGeneration;
				pendingJournalRef.current = {
					snapshot,
					idempotencyKey: crypto.randomUUID(),
					coveredSnapshots: coveredSnapshotsRef.current,
					changeGeneration,
				};
			} catch (error) {
				syncRejectedRef.current = true;
				setSyncRejected(true);
				setSaveMessage(
					error instanceof Error ? error.message : "本地草稿保存失败。",
				);
				return;
			}
		}
		setLocalStatus("正在重新检查同步；本地 Yjs 修改仍已保留。");
		runPendingJournal.current();
	}

	async function save() {
		if (persistTimer.current !== null) {
			window.clearTimeout(persistTimer.current);
			persistTimer.current = null;
		}
		const changeGeneration = documentChangeGenerationRef.current;
		try {
			const snapshot = await resourceRuntime.persistLocalState(
				accountId,
				resourceId,
				document.exportState(),
				cache,
			);
			latestSnapshotRef.current = snapshot;
			persistedChangeGenerationRef.current = Math.max(
				persistedChangeGenerationRef.current,
				changeGeneration,
			);
			hasUnconfirmedLocalChangesRef.current =
				snapshot.revision > snapshot.durableRevision;
			setStorageMessage("已保存在此设备。");
			if (canQueueJournal() && hasUnconfirmedLocalChangesRef.current) {
				pendingJournalRef.current = {
					snapshot,
					idempotencyKey: crypto.randomUUID(),
					coveredSnapshots: coveredSnapshotsRef.current,
					changeGeneration,
				};
				setLocalStatus("本地修改已保存，正在同步到服务器…");
				runPendingJournal.current();
			} else if (!navigator.onLine) {
				setLocalStatus("离线中；本地修改已保存，联网后将自动同步。");
			} else {
				setLocalStatus("本地修改已保存。");
			}
			setSaveMessage("已保存在此设备。");
		} catch (error) {
			setSaveMessage(
				error instanceof Error ? error.message : "保存失败，请重试。",
			);
		}
	}

	async function returnToWorkspace(navigateAway: () => void = onBack) {
		if (leavingEditor) return;
		setLeavingEditor(true);
		if (persistTimer.current !== null) {
			window.clearTimeout(persistTimer.current);
			persistTimer.current = null;
		}
		try {
			while (
				persistedChangeGenerationRef.current <
				documentChangeGenerationRef.current
			) {
				if (persistTimer.current !== null) {
					window.clearTimeout(persistTimer.current);
					persistTimer.current = null;
				}
				const changeGeneration = documentChangeGenerationRef.current;
				const snapshot = await resourceRuntime.persistLocalState(
					accountId,
					resourceId,
					document.exportState(),
					cache,
				);
				latestSnapshotRef.current = snapshot;
				persistedChangeGenerationRef.current = changeGeneration;
				hasUnconfirmedLocalChangesRef.current =
					snapshot.revision > snapshot.durableRevision;
				setStorageMessage("已保存在此设备。");
			}
		} catch (error) {
			setLeavingEditor(false);
			setStorageMessage(
				error instanceof Error ? error.message : "本地草稿保存失败。",
			);
			setLocalStatus("当前修改尚未确认写入本地缓存；请留在编辑器重试保存。");
			return;
		}
		navigateAway();
	}

	return (
		<div className="editor-shell">
			<header className="editor-topbar">
				<div className="editor-nav-left">
					<button
						type="button"
						className="btn-editor-back"
						data-testid="editor-back"
						disabled={leavingEditor}
						aria-busy={leavingEditor}
						onClick={() => void returnToWorkspace()}
					>
						<span aria-hidden="true">‹</span>
						{leavingEditor ? "正在保存本地修改…" : "返回管理台"}
					</button>
					<nav
						className="breadcrumb-trail editor-breadcrumb"
						aria-label="编辑器位置"
						data-testid="editor-breadcrumb"
					>
						<button
							type="button"
							className="breadcrumb-item"
							disabled={leavingEditor}
							onClick={() =>
								void returnToWorkspace(() =>
									navigate(
										`/workspace?workspaceId=${encodeURIComponent(tree.data?.workspaceId ?? "")}`,
									),
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
					<span className="editor-status-line" data-testid="realtime-status">
						{realtimeStatus}
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
							<span data-testid="editor-presence">
								{realtimeStatus === "connected"
									? "实时协同已连接"
									: `协同状态：${realtimeStatus}`}
							</span>
							<span
								className="journal-badge-editor"
								data-testid="editor-journal-seq"
							>
								#{journalSeq} ops
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
						</p>
						<p
							className="editor-status-line"
							data-testid="editor-offline-status"
						>
							{localStatus ||
								storageMessage ||
								(opened.source === "offline-cache" ? "离线缓存" : "")}
						</p>
						{syncRejected && (
							<div
								className="editor-status-line"
								data-testid="editor-sync-rejected-actions"
							>
								<button type="button" onClick={exportLocalYjsDraft}>
									下载本地备份
								</button>
								{!sessionReplaced && (
									<button
										type="button"
										onClick={() => void retryRejectedSync()}
									>
										重试同步
									</button>
								)}
							</div>
						)}
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
									系统不会猜测它属于哪份文档。选择复制到当前资源后，请检查内容是否正确。
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
						{(
							[
								"comments",
								"history",
								"ai",
								"assets",
								"share",
								"importexport",
							] as const
						).map((name) => (
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
												: name === "ai"
													? "sparkle"
													: name === "share"
														? "workspace"
														: name === "importexport"
															? "folder"
															: "document"
									}
									size={14}
								/>
								<span>
									{name === "comments"
										? "评论"
										: name === "history"
											? "历史"
											: name === "ai"
												? "AI 提案"
												: name === "assets"
													? "附件"
													: name === "share"
														? "分享"
														: "导入/导出"}
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
					<div className="drawer-tab-pane active" hidden={tab !== "assets"}>
						<AssetsPanel
							resourceId={resourceId}
							onInsertAssets={(references: readonly NewAssetReference[]) => {
								if (!editorSurface.current) {
									throw new Error("编辑器尚未准备好，附件已上传但未插入正文。");
								}
								inlineAssetRenderer.current?.invalidateMetadata();
								editorSurface.current.insertAssets(references);
							}}
						/>
					</div>
					<div className="drawer-tab-pane active" hidden={tab !== "share"}>
						<SharePanel resourceId={resourceId} />
					</div>
					<div
						className="drawer-tab-pane active"
						hidden={tab !== "importexport"}
					>
						<ImportExportPanel
							resourceId={resourceId}
							onImported={reloadContentFromServer}
						/>
					</div>
				</aside>
			</div>
		</div>
	);
}
