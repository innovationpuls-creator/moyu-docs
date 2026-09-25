import type { OpenPublicSharedResourceResponse } from "@dom/client-sdk";
import {
	type AssetReference,
	type ContentNode,
	createTextDocument,
	type TextDocument,
	type TextEditorSurface,
} from "@dom/editor-core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { client } from "../../shared/api/client";
import { createPublicShareClient } from "../../shared/realtime";

interface SharePanelProps {
	resourceId: string;
}

function restoreCheckpoint(model: TextDocument, snapshot: unknown): boolean {
	if (typeof snapshot !== "object" || snapshot === null) return false;
	const checkpoint = snapshot as { nodes?: unknown; text?: unknown };
	if (Array.isArray(checkpoint.nodes)) {
		model.setNodes(checkpoint.nodes as ContentNode[]);
		return true;
	}
	if (typeof checkpoint.text === "string") {
		model.setText(checkpoint.text);
		return true;
	}
	return false;
}

function renderSharedAsset(token: string) {
	return (container: HTMLElement, reference: AssetReference) => {
		const url = client.publicSharedAssetUrl(token, reference.assetId);
		if (reference.kind === "image") {
			const image = container as HTMLImageElement;
			image.src = url;
			image.referrerPolicy = "no-referrer";
			return () => image.removeAttribute("src");
		}

		let disposed = false;
		const link = window.document.createElement("a");
		link.href = url;
		link.target = "_blank";
		link.rel = "noreferrer";
		link.referrerPolicy = "no-referrer";
		link.textContent = reference.label || "附件";
		void client
			.downloadPublicSharedAsset(token, reference.assetId)
			.then(async (blob) => {
				const mime = blob.type.split(";", 1)[0].trim().toLowerCase();
				if (mime !== "text/plain" || blob.size > 64 * 1024) {
					if (!disposed) container.replaceChildren(link);
					return;
				}
				const text = await blob.text();
				if (disposed) return;
				container.style.whiteSpace = "pre-wrap";
				container.replaceChildren(
					window.document.createTextNode(text),
					window.document.createElement("br"),
					link,
				);
			})
			.catch(() => {
				if (!disposed) container.replaceChildren(link);
			});
		return () => {
			disposed = true;
		};
	};
}

function PublicShareDocument({
	token,
	resource,
}: {
	token: string;
	resource: OpenPublicSharedResourceResponse;
}) {
	const host = useRef<HTMLDivElement>(null);
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		const element = host.current;
		if (!element) return;
		let disposed = false;
		let model: TextDocument | null = null;
		let surface: TextEditorSurface | null = null;
		type ShareConnection = {
			client: ReturnType<typeof createPublicShareClient>;
			unsubscribe: () => void;
			stateKind: "yjs" | "checkpoint" | null;
			closed: boolean;
		};
		let primary: ShareConnection | null = null;
		let candidate: ShareConnection | null = null;
		let refreshRequested = false;
		let refreshInProgress = false;
		let refreshTimer: ReturnType<typeof setTimeout> | null = null;
		setError("");
		setLoading(true);
		const installModel = (next: TextDocument) => {
			surface?.destroy();
			model?.destroy();
			element.replaceChildren();
			model = next;
			surface = next.mountEditor(element, {
				readOnly: true,
				renderAsset: renderSharedAsset(token),
			});
		};
		const installCheckpoint = (snapshot: unknown) => {
			const next = createTextDocument();
			if (!restoreCheckpoint(next, snapshot)) {
				next.destroy();
				throw new Error("公开快照中没有可显示的文档内容。");
			}
			// Checkpoint edits are local initialization only; never publish them.
			next.flushLocalUpdates();
			installModel(next);
		};
		const closeConnection = (connection: ShareConnection | null) => {
			if (!connection || connection.closed) return;
			connection.closed = true;
			connection.unsubscribe();
			connection.client.close();
		};
		const finishRefresh = () => {
			refreshInProgress = false;
			if (refreshRequested) scheduleRefresh();
		};
		const promote = (connection: ShareConnection, update: Uint8Array) => {
			// A yjs share-state is followed by a full current-state sync.update.
			// Rebuilding avoids merging it with a checkpoint or legacy Y.Text model.
			const next = createTextDocument(update);
			installModel(next);
			setError("");
			setLoading(false);
			if (connection === candidate) {
				const previous = primary;
				primary = connection;
				candidate = null;
				refreshRequested = false;
				finishRefresh();
				closeConnection(previous);
			} else {
				primary = connection;
			}
		};
		const scheduleRefresh = () => {
			refreshRequested = true;
			if (refreshInProgress || refreshTimer !== null || disposed) return;
			refreshTimer = setTimeout(() => {
				refreshTimer = null;
				if (!refreshRequested || disposed) return;
				refreshRequested = false;
				refreshInProgress = true;
				startConnection("candidate");
			}, 100);
		};
		const startConnection = (role: "primary" | "candidate") => {
			const realtime = createPublicShareClient(token);
			const connection: ShareConnection = {
				client: realtime,
				unsubscribe: () => {},
				stateKind: null,
				closed: false,
			};
			if (role === "candidate") candidate = connection;
			else primary = connection;
			connection.unsubscribe = realtime.subscribeResource(resource.resourceId, {
				getStateVector: () => new Uint8Array(),
				getLocalState: () => new Uint8Array(),
				onUpdate(update) {
					if (disposed || connection.closed) return;
					if (connection.stateKind === "checkpoint") {
						// A checkpoint is not a Yjs base state. Treat deltas only as
						// invalidation signals and obtain a fresh public checkpoint.
						scheduleRefresh();
						return;
					}
					if (connection.stateKind !== "yjs") return;
					try {
						if (role === "candidate" || model === null) {
							promote(connection, update);
						} else {
							model.applyRemoteUpdate(update);
							setLoading(false);
						}
					} catch (updateError) {
						setError(
							updateError instanceof Error
								? updateError.message
								: "读取实时文档状态失败。",
						);
						setLoading(false);
						if (connection === candidate) {
							candidate = null;
							closeConnection(connection);
							finishRefresh();
						}
					}
				},
				onPeers: () => {},
				onShareState(kind) {
					if (disposed || connection.closed) return;
					connection.stateKind = kind;
					setError("");
					if (kind === "yjs") {
						if (role === "primary" && model === null) setLoading(true);
						return;
					}
					if (role === "primary") {
						try {
							installCheckpoint(resource.snapshot);
							setLoading(false);
						} catch (restoreError) {
							setError(
								restoreError instanceof Error
									? restoreError.message
									: "读取公开快照失败。",
							);
							setLoading(false);
						}
						return;
					}
					void client
						.openPublicSharedResource(token)
						.then((latest) => {
							if (disposed || connection.closed) return;
							if (latest.resourceId !== resource.resourceId) {
								throw new Error("分享文档已发生变化，请重新打开链接。");
							}
							installCheckpoint(latest.snapshot);
							setError("");
						})
						.catch((restoreError: unknown) => {
							if (disposed || connection.closed) return;
							setError(
								restoreError instanceof Error
									? restoreError.message
									: "刷新公开快照失败。",
							);
						})
						.finally(() => {
							if (connection === candidate) {
								candidate = null;
								closeConnection(connection);
								finishRefresh();
							}
						});
				},
				onStatus(status) {
					if (disposed || connection.closed || status !== "denied") return;
					if (connection === candidate) {
						candidate = null;
						closeConnection(connection);
						finishRefresh();
					}
					setError("分享链接已失效或无权读取实时内容。");
					setLoading(false);
				},
			});
		};
		startConnection("primary");
		return () => {
			disposed = true;
			if (refreshTimer !== null) clearTimeout(refreshTimer);
			closeConnection(candidate);
			closeConnection(primary);
			surface?.destroy();
			model?.destroy();
		};
	}, [resource, token]);

	return (
		<section
			className="public-share-content"
			aria-label="文档内容"
			aria-busy={loading}
		>
			{error && <p role="alert">{error}</p>}
			{loading && !error && <p role="status">正在读取文档内容…</p>}
			<div
				className="public-share-editor"
				ref={host}
				data-testid="public-share-content-editor"
			/>
		</section>
	);
}

function expiresAtValue(value: string): string | null {
	if (!value) return null;
	const date = new Date(value);
	return Number.isNaN(date.valueOf()) ? null : date.toISOString();
}

function dateTimeInput(value: string | null): string {
	if (!value) return "";
	const date = new Date(value);
	const local = new Date(date.valueOf() - date.getTimezoneOffset() * 60_000);
	return local.toISOString().slice(0, 16);
}

function oneTimeShareUrl(value: string): string {
	try {
		return new URL(value, window.location.origin).toString();
	} catch {
		return value;
	}
}

export function SharePanel({ resourceId }: SharePanelProps) {
	const queryClient = useQueryClient();
	const [newExpiry, setNewExpiry] = useState("");
	const [oneTimeUrl, setOneTimeUrl] = useState("");
	const [message, setMessage] = useState("");
	const shares = useQuery({
		queryKey: ["resource-share-links", resourceId],
		queryFn: () => client.listResourceShareLinks(resourceId),
		retry: false,
	});
	const invalidate = () =>
		queryClient.invalidateQueries({
			queryKey: ["resource-share-links", resourceId],
		});
	const create = useMutation({
		mutationFn: () =>
			client.createResourceShareLink(resourceId, {
				expiresAt: expiresAtValue(newExpiry),
			}),
		onSuccess: async (result) => {
			setOneTimeUrl(result.shareUrl);
			setMessage("分享链接已创建。完整链接只在创建或重新生成时显示一次。");
			await invalidate();
		},
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "创建分享链接失败。"),
	});
	const changeExpiry = useMutation({
		mutationFn: ({
			shareId,
			expiresAt,
		}: {
			shareId: string;
			expiresAt: string | null;
		}) => client.setResourceShareLinkExpiry(resourceId, shareId, { expiresAt }),
		onSuccess: async () => {
			setMessage("分享链接有效期已更新。");
			await invalidate();
		},
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "更新有效期失败。"),
	});
	const revoke = useMutation({
		mutationFn: (shareId: string) =>
			client.revokeResourceShareLink(resourceId, shareId),
		onSuccess: async () => {
			setMessage("分享链接已撤销。");
			await invalidate();
		},
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "撤销分享链接失败。"),
	});
	const regenerate = useMutation({
		mutationFn: (shareId: string) =>
			client.regenerateResourceShareLink(resourceId, shareId, {
				expiresAt: expiresAtValue(newExpiry),
			}),
		onSuccess: async (result) => {
			setOneTimeUrl(result.shareUrl);
			setMessage("已重新生成链接。旧链接已失效，请复制新链接。");
			await invalidate();
		},
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "重新生成失败。"),
	});

	async function copyOneTimeUrl() {
		try {
			await navigator.clipboard.writeText(oneTimeShareUrl(oneTimeUrl));
			setMessage("链接已复制。请妥善保管；之后无法从列表中再次查看。");
		} catch (error) {
			setMessage(
				error instanceof Error ? error.message : "复制失败，请手动复制链接。",
			);
		}
	}

	return (
		<section
			className="share-panel"
			aria-label="文档分享"
			data-testid="share-panel"
		>
			<header className="share-panel-heading">
				<div>
					<h2>只读分享</h2>
					<p>
						任何持有链接的人都能查看此文档，不能编辑、评论或查看协作者状态。
					</p>
				</div>
			</header>
			<label className="share-expiry-field">
				<span>有效期（留空表示永久有效）</span>
				<input
					aria-label="新链接有效期"
					data-testid="share-new-expiry"
					type="datetime-local"
					value={newExpiry}
					onChange={(event) => setNewExpiry(event.currentTarget.value)}
				/>
			</label>
			<button
				type="button"
				className="share-primary-button"
				data-testid="share-create"
				disabled={create.isPending}
				onClick={() => create.mutate()}
			>
				{create.isPending ? "正在创建…" : "创建只读链接"}
			</button>
			{oneTimeUrl && (
				<div className="share-secret-result" data-testid="share-one-time-url">
					<label>
						<span>新链接仅显示在这里</span>
						<input
							readOnly
							value={oneTimeShareUrl(oneTimeUrl)}
							aria-label="刚创建的只读链接"
							onFocus={(event) => event.currentTarget.select()}
						/>
					</label>
					<button type="button" onClick={() => void copyOneTimeUrl()}>
						复制链接
					</button>
				</div>
			)}
			{message && (
				<p
					className="share-panel-message"
					role="status"
					data-testid="share-message"
				>
					{message}
				</p>
			)}
			<div className="share-link-list">
				<h3>链接管理</h3>
				{shares.isLoading ? (
					<p className="share-empty-state">正在读取分享链接…</p>
				) : shares.isError ? (
					<div className="share-error" role="alert">
						<p>{shares.error.message}</p>
						<button type="button" onClick={() => void shares.refetch()}>
							重试
						</button>
					</div>
				) : shares.data?.shareLinks.length ? (
					<ul>
						{shares.data.shareLinks.map((share) => (
							<li className="share-link-row" key={share.shareId}>
								<div className="share-link-meta">
									<strong>
										{share.status === "Active"
											? "有效"
											: share.status === "Expired"
												? "已过期"
												: "已撤销"}
									</strong>
									<span>
										{share.expiresAt
											? `到期时间：${new Date(share.expiresAt).toLocaleString()}`
											: "永久有效"}
									</span>
								</div>
								{share.status !== "Revoked" && (
									<div className="share-link-controls">
										<label>
											<span className="visually-hidden">修改有效期</span>
											<input
												aria-label={`修改有效期 ${share.shareId}`}
												type="datetime-local"
												defaultValue={dateTimeInput(share.expiresAt)}
												onBlur={(event) => {
													const value = event.currentTarget.value;
													if (expiresAtValue(value) === share.expiresAt) return;
													changeExpiry.mutate({
														shareId: share.shareId,
														expiresAt: expiresAtValue(value),
													});
												}}
											/>
										</label>
										<button
											type="button"
											disabled={regenerate.isPending}
											onClick={() => regenerate.mutate(share.shareId)}
										>
											重新生成
										</button>
										<button
											type="button"
											disabled={revoke.isPending}
											onClick={() => revoke.mutate(share.shareId)}
										>
											撤销
										</button>
									</div>
								)}
							</li>
						))}
					</ul>
				) : (
					<p className="share-empty-state">还没有创建分享链接。</p>
				)}
			</div>
		</section>
	);
}

export function PublicSharePage() {
	const { token = "" } = useParams();
	const resource = useQuery({
		queryKey: ["public-share", token],
		queryFn: () => client.openPublicSharedResource(token),
		enabled: token.length > 0,
		gcTime: 0,
		refetchOnMount: "always",
		retry: false,
	});

	if (resource.isLoading || resource.isFetching) {
		return (
			<main className="public-share-stage" data-testid="public-share-loading">
				<p>正在打开只读分享…</p>
			</main>
		);
	}
	if (resource.isError || !resource.data) {
		return (
			<main
				className="public-share-stage"
				data-testid="public-share-unavailable"
			>
				<section className="public-share-paper" role="alert">
					<h1>链接不可用</h1>
					<p>分享链接可能已撤销、过期，或输入有误。</p>
				</section>
			</main>
		);
	}

	return (
		<main className="public-share-stage" data-testid="public-share-viewer">
			<article className="public-share-paper">
				<header>
					<p>墨屿 · 只读分享</p>
					<h1>{resource.data.name}</h1>
					<span>只读 · {resource.data.resourceType}</span>
				</header>
				<PublicShareDocument token={token} resource={resource.data} />
			</article>
		</main>
	);
}
