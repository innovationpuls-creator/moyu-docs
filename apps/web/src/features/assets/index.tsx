import { createIdempotencyKey } from "@dom/client-sdk";
import type { NewAssetReference } from "@dom/editor-core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { client } from "../../shared/api/client";

interface AssetsPanelProps {
	resourceId: string;
	onInsertAssets(references: readonly NewAssetReference[]): void;
}

function formatSize(sizeBytes: number): string {
	if (sizeBytes < 1024) return `${sizeBytes} B`;
	if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
	return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isPreviewableImage(mime: string | null): boolean {
	return mime !== null && /^image\/(avif|gif|jpeg|png|webp)$/i.test(mime);
}

function AssetPreview({
	resourceId,
	assetId,
	name,
}: {
	resourceId: string;
	assetId: string;
	name: string;
}) {
	const [previewUrl, setPreviewUrl] = useState("");
	const preview = useQuery({
		queryKey: ["resource-asset-preview", resourceId, assetId],
		queryFn: () => client.downloadAsset(assetId),
		retry: false,
	});

	useEffect(() => {
		if (!preview.data) return;
		const url = URL.createObjectURL(preview.data);
		setPreviewUrl(url);
		return () => URL.revokeObjectURL(url);
	}, [preview.data]);

	if (preview.isLoading)
		return <span className="asset-preview-pending">加载预览…</span>;
	if (preview.isError || !previewUrl) return null;
	return <img className="asset-preview-image" src={previewUrl} alt={name} />;
}

function referenceFromAsset(asset: {
	assetId: string;
	originalName: string;
	mime: string | null;
}): NewAssetReference {
	return {
		kind: isPreviewableImage(asset.mime) ? "image" : "attachment",
		assetId: asset.assetId,
		label: asset.originalName,
	};
}

interface FailedUpload {
	file: File;
	message: string;
}

export function AssetsPanel({ resourceId, onInsertAssets }: AssetsPanelProps) {
	const queryClient = useQueryClient();
	const fileInput = useRef<HTMLInputElement>(null);
	const uploadKeys = useRef(new Map<File, string>());
	const [message, setMessage] = useState("");
	const [failedUploads, setFailedUploads] = useState<FailedUpload[]>([]);
	const assets = useQuery({
		queryKey: ["resource-assets", resourceId],
		queryFn: () => client.listResourceAssets(resourceId),
		retry: false,
	});
	const upload = useMutation({
		mutationFn: async (files: File[]) => {
			const uploaded: Array<{ assetId: string; file: File }> = [];
			const failed: FailedUpload[] = [];
			for (const file of files) {
				let key = uploadKeys.current.get(file);
				if (!key) {
					key = createIdempotencyKey();
					uploadKeys.current.set(file, key);
				}
				try {
					const result = await client.uploadAsset(resourceId, file, key);
					uploadKeys.current.delete(file);
					uploaded.push({ assetId: result.assetId, file });
				} catch (error) {
					const reason = error instanceof Error ? error.message : "未知错误";
					failed.push({ file, message: reason });
				}
			}
			let metadata: Awaited<
				ReturnType<typeof client.listResourceAssets>
			>["assets"] = [];
			let metadataUnavailable = false;
			if (uploaded.length > 0) {
				try {
					metadata = (await client.listResourceAssets(resourceId)).assets;
				} catch {
					metadataUnavailable = true;
				}
			}
			const references = uploaded.map(({ assetId, file }) => {
				const asset = metadata.find((item) => item.assetId === assetId);
				return {
					file,
					reference: {
						kind: isPreviewableImage(asset?.mime ?? file.type)
							? ("image" as const)
							: ("attachment" as const),
						assetId,
						label: asset?.originalName ?? file.name,
					},
				};
			});
			return { uploaded: references, failed, metadataUnavailable };
		},
		onSuccess: async ({ uploaded, failed, metadataUnavailable }) => {
			setFailedUploads((current) => {
				const succeeded = new Set(uploaded.map(({ file }) => file));
				const next = current.filter(({ file }) => !succeeded.has(file));
				for (const failure of failed) {
					const existing = next.findIndex(({ file }) => file === failure.file);
					if (existing === -1) next.push(failure);
					else next[existing] = failure;
				}
				return next;
			});
			let insertionError = "";
			try {
				onInsertAssets(uploaded.map(({ reference }) => reference));
			} catch (error) {
				insertionError = error instanceof Error ? error.message : "未知错误";
			}
			await queryClient.invalidateQueries({
				queryKey: ["resource-assets", resourceId],
			});
			setMessage(
				insertionError
					? `已上传 ${uploaded.length} 个附件，但正文插入失败：${insertionError}。可在附件列表中重试。`
					: failed.length === 0
						? `已上传并插入正文 ${uploaded.length} 个附件${metadataUnavailable ? "；文件类型未能确认，附件信息可能需要刷新" : ""}。`
						: `已上传并插入正文 ${uploaded.length} 个；${failed.length} 个失败：${failed.map(({ file, message: reason }) => `${file.name}（${reason}）`).join("、")}${metadataUnavailable ? "；文件类型未能确认" : ""}`,
			);
		},
	});

	async function download(asset: { assetId: string; originalName: string }) {
		try {
			const blob = await client.downloadAsset(asset.assetId);
			const url = URL.createObjectURL(blob);
			const anchor = window.document.createElement("a");
			anchor.href = url;
			anchor.download = asset.originalName;
			anchor.click();
			window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
		} catch (error) {
			setMessage(error instanceof Error ? error.message : "附件下载失败。");
		}
	}

	function insert(asset: {
		assetId: string;
		originalName: string;
		mime: string | null;
	}) {
		try {
			onInsertAssets([referenceFromAsset(asset)]);
			setMessage(`已插入正文：${asset.originalName}`);
		} catch (error) {
			setMessage(error instanceof Error ? error.message : "附件插入失败。");
		}
	}

	return (
		<section className="assets-panel" aria-label="文档附件">
			<div className="assets-panel-heading">
				<div>
					<h2>附件</h2>
					<p>图片可预览，其他文件可下载。</p>
				</div>
				<input
					ref={fileInput}
					type="file"
					multiple
					hidden
					data-testid="asset-upload-input"
					onChange={(event) => {
						const files = Array.from(event.currentTarget.files ?? []);
						if (files.length > 0) upload.mutate(files);
						event.currentTarget.value = "";
					}}
				/>
				<button
					type="button"
					className="asset-upload-button"
					data-testid="asset-upload-button"
					disabled={upload.isPending}
					onClick={() => fileInput.current?.click()}
				>
					{upload.isPending ? "正在上传…" : "上传附件"}
				</button>
			</div>
			{message && <p className="assets-panel-message">{message}</p>}
			{failedUploads.length > 0 && (
				<ul className="assets-upload-failures" aria-label="上传失败的附件">
					{failedUploads.map(({ file, message: reason }, index) => (
						<li key={`${file.name}:${file.size}:${file.lastModified}`}>
							<span>
								{file.name}：{reason}
							</span>
							<button
								type="button"
								data-testid={`asset-upload-retry-${index}`}
								disabled={upload.isPending}
								onClick={() => upload.mutate([file])}
							>
								重新上传
							</button>
						</li>
					))}
				</ul>
			)}
			{assets.isLoading ? (
				<p className="assets-panel-empty">正在读取附件…</p>
			) : assets.isError ? (
				<div className="assets-panel-error" role="alert">
					<p>{assets.error.message}</p>
					<button type="button" onClick={() => void assets.refetch()}>
						重试
					</button>
				</div>
			) : assets.data?.assets.length ? (
				<ul className="asset-list" data-testid="asset-list">
					{assets.data.assets.map((asset) => {
						const isPreviewable = isPreviewableImage(asset.mime);
						return (
							<li className="asset-list-item" key={asset.assetId}>
								{isPreviewable && (
									<AssetPreview
										resourceId={resourceId}
										assetId={asset.assetId}
										name={asset.originalName}
									/>
								)}
								<div className="asset-list-details">
									<strong title={asset.originalName}>
										{asset.originalName}
									</strong>
									<span>
										{asset.mime ?? "未知类型"} · {formatSize(asset.sizeBytes)}
									</span>
								</div>
								<div className="asset-actions">
									<button
										type="button"
										className="asset-insert-button"
										data-testid={`asset-insert-${asset.assetId}`}
										onClick={() => insert(asset)}
									>
										插入正文
									</button>
									<button
										type="button"
										className="asset-download-button"
										data-testid={`asset-download-${asset.assetId}`}
										onClick={() => void download(asset)}
									>
										下载
									</button>
								</div>
							</li>
						);
					})}
				</ul>
			) : (
				<p className="assets-panel-empty" data-testid="asset-empty-state">
					还没有附件。
				</p>
			)}
		</section>
	);
}
