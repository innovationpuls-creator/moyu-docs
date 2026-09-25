import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { client } from "../../shared/api/client";

type ResourceTask = Awaited<ReturnType<typeof client.getTask>>["task"];
type ImportDocument = Parameters<typeof client.importResource>[1];

const activeStates = new Set<ResourceTask["state"]>([
	"Created",
	"Queued",
	"Running",
	"WaitingForUser",
	"Retrying",
]);

function isResourceExchangeDocument(value: unknown): value is ImportDocument {
	if (typeof value !== "object" || value === null || Array.isArray(value))
		return false;
	const document = value as Partial<ImportDocument>;
	const resource = document.resource;
	const content = document.content;
	return (
		document.kind === "dom.resource.export.v1" &&
		document.schemaVersion === "1.0.0" &&
		typeof document.exportedAt === "string" &&
		typeof resource === "object" &&
		resource !== null &&
		typeof resource.resourceId === "string" &&
		typeof resource.name === "string" &&
		typeof content === "object" &&
		content !== null &&
		typeof content.journalSeq === "number" &&
		(content.snapshot === null ||
			(typeof content.snapshot === "object" && content.snapshot !== null))
	);
}

function triggerDownload(blob: Blob, fileName: string) {
	const url = URL.createObjectURL(blob);
	const anchor = window.document.createElement("a");
	anchor.href = url;
	anchor.download = fileName;
	anchor.click();
	window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function ImportExportPanel({
	resourceId,
	onImported,
}: {
	resourceId: string;
	onImported?(): Promise<void>;
}) {
	const navigate = useNavigate();
	const fileInput = useRef<HTMLInputElement>(null);
	const lastReloadedTaskId = useRef("");
	const [trackedTaskId, setTrackedTaskId] = useState("");
	const [exportSessionId, setExportSessionId] = useState("");
	const [message, setMessage] = useState("");
	const task = useQuery({
		queryKey: ["task", trackedTaskId],
		queryFn: () => client.getTask(trackedTaskId),
		enabled: !!trackedTaskId,
		refetchInterval: (query) =>
			query.state.data && activeStates.has(query.state.data.task.state)
				? 1_500
				: false,
	});
	const importDocument = useMutation({
		mutationFn: async (file: File) => {
			if (file.size > 10 * 1024 * 1024)
				throw new Error("文件超过 10 MiB，请选择较小的导出文件。");
			let parsed: unknown;
			try {
				parsed = JSON.parse(await file.text());
			} catch {
				throw new Error("文件不是有效的 JSON 文档。");
			}
			if (!isResourceExchangeDocument(parsed))
				throw new Error("文件不是 DOM 文档导出格式。");
			return client.importResource(resourceId, parsed, crypto.randomUUID());
		},
		onSuccess: (result) => {
			setExportSessionId("");
			setTrackedTaskId(result.taskId);
			setMessage("导入已排入任务中心，完成后会重新载入文档。");
		},
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "导入失败，请重试。"),
	});
	const createExport = useMutation({
		mutationFn: () =>
			client.createResourceExportTask(resourceId, crypto.randomUUID()),
		onSuccess: (result) => {
			setTrackedTaskId(result.taskId);
			setExportSessionId(result.exportSessionId);
			setMessage("导出已排入任务中心。完成后可下载 JSON 文件。");
		},
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "导出任务创建失败。"),
	});
	const downloadExport = useMutation({
		mutationFn: async () => {
			if (!exportSessionId) throw new Error("没有可下载的导出结果。");
			const blob = await client.getResourceExportResult(
				resourceId,
				exportSessionId,
			);
			triggerDownload(blob, "resource-export.json");
		},
		onSuccess: () => setMessage("导出文件已下载。"),
		onError: (error) =>
			setMessage(error instanceof Error ? error.message : "下载导出文件失败。"),
	});
	const taskDetail = task.data?.task;

	useEffect(() => {
		if (
			taskDetail?.state !== "Succeeded" ||
			!taskDetail.taskType.startsWith("import.") ||
			lastReloadedTaskId.current === taskDetail.taskId
		)
			return;
		lastReloadedTaskId.current = taskDetail.taskId;
		setMessage("导入完成，正在载入服务器上的最新内容…");
		void onImported?.().then(
			() => setMessage("导入完成，文档已更新。"),
			() => setMessage("导入完成，但重新载入文档失败，请刷新后重试。"),
		);
	}, [onImported, taskDetail]);

	const taskProgress = taskDetail?.percentage;
	const isTaskActive = taskDetail ? activeStates.has(taskDetail.state) : false;
	return (
		<section className="import-export-panel" aria-label="导入和导出">
			<div className="import-export-heading">
				<div>
					<h2>文档迁移</h2>
					<p>使用 DOM JSON 格式备份、迁移或恢复文档快照。</p>
				</div>
			</div>
			<div className="import-export-actions">
				<input
					ref={fileInput}
					type="file"
					accept=".json,application/json"
					hidden
					data-testid="resource-import-input"
					onChange={(event) => {
						const file = event.currentTarget.files?.[0];
						if (file) importDocument.mutate(file);
						event.currentTarget.value = "";
					}}
				/>
				<button
					type="button"
					data-testid="resource-import-button"
					disabled={importDocument.isPending || isTaskActive}
					onClick={() => fileInput.current?.click()}
				>
					{importDocument.isPending ? "正在读取…" : "导入 JSON"}
				</button>
				<button
					type="button"
					data-testid="resource-export-button"
					disabled={createExport.isPending || isTaskActive}
					onClick={() => createExport.mutate()}
				>
					{createExport.isPending ? "正在提交…" : "导出 JSON"}
				</button>
			</div>
			{message && (
				<p className="import-export-message" role="status" aria-live="polite">
					{message}
				</p>
			)}
			{task.isError && (
				<div className="import-export-error" role="alert">
					<span>任务进度暂时不可用。</span>
					<button type="button" onClick={() => void task.refetch()}>
						重试查询
					</button>
				</div>
			)}
			{taskDetail && (
				<div className="import-export-task" data-testid="resource-task-status">
					<div>
						<strong>
							{taskDetail.state === "Succeeded"
								? "已完成"
								: taskDetail.state === "Failed"
									? "失败"
									: taskDetail.state === "Cancelled"
										? "已取消"
										: "处理中"}
						</strong>
						{taskDetail.stage && <span> · {taskDetail.stage}</span>}
						{typeof taskProgress === "number" && (
							<span> · {Math.round(taskProgress)}%</span>
						)}
					</div>
					{taskDetail.failureCode && (
						<small>错误代码：{taskDetail.failureCode}</small>
					)}
					<div className="import-export-task-actions">
						{exportSessionId && taskDetail.state === "Succeeded" && (
							<button
								type="button"
								disabled={downloadExport.isPending}
								onClick={() => downloadExport.mutate()}
							>
								{downloadExport.isPending ? "正在下载…" : "下载导出文件"}
							</button>
						)}
						<button type="button" onClick={() => navigate("/tasks")}>
							打开任务中心
						</button>
					</div>
				</div>
			)}
		</section>
	);
}
