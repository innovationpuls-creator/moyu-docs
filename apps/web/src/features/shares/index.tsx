import type { OpenPublicSharedResourceResponse } from "@dom/client-sdk";
import {
	type AssetReference,
	createTextDocument,
	type TextDocument,
	type TextEditorSurface,
} from "@dom/editor-core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { client } from "../../shared/api/client";

interface SharePanelProps {
	resourceId: string;
}

function snapshotText(snapshot: unknown): string | null {
	if (typeof snapshot !== "object" || snapshot === null) return null;
	const text = (snapshot as { text?: unknown }).text;
	return typeof text === "string" ? text : null;
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

		const link = document.createElement("a");
		link.href = url;
		link.rel = "noopener noreferrer";
		link.referrerPolicy = "no-referrer";
		link.textContent = reference.label || "附件";
		container.replaceChildren(link);
		let disposed = false;
		void client
			.downloadPublicSharedAsset(token, reference.assetId)
			.then(async (blob) => {
				if (
					disposed ||
					blob.type.toLowerCase().split(";")[0] !== "text/plain" ||
					blob.size > 128 * 1024
				)
					return;
				const preview = document.createElement("pre");
				preview.textContent = await blob.text();
				if (!disposed) container.replaceChildren(preview);
			})
			.catch(() => {
				if (!disposed)
					link.textContent = `${reference.label || "附件"}（读取失败，可重试）`;
			});
		return () => {
			disposed = true;
			container.replaceChildren();
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
		setError("");
		setLoading(true);
		model = createTextDocument();
		const text = snapshotText(resource.snapshot);
		if (text === null) {
			setError("当前文档尚无可公开的内容快照。");
			setLoading(false);
		} else {
			model.setText(text);
			model.flushLocalUpdates();
			surface = model.mountEditor(element, {
				readOnly: true,
				renderAsset: renderSharedAsset(token),
			});
			setLoading(false);
		}
		return () => {
			disposed = true;
			surface?.destroy();
			model?.destroy();
		};
	}, [resource, token]);

	if (error) return <p role="alert">{error}</p>;
	return (
		<section
			className="public-share-content"
			aria-label="文档内容"
			aria-busy={loading}
		>
			{loading && <p role="status">正在读取文档内容…</p>}
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
