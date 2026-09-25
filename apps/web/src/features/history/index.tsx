import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { client } from "../../shared/api/client";
import { formatConsoleDate } from "../../shared/ui/date";

type RestoreTask = Awaited<ReturnType<typeof client.getTask>>["task"];

const activeTaskStates = new Set<RestoreTask["state"]>([
	"Created",
	"Queued",
	"Running",
	"WaitingForUser",
	"Retrying",
]);

function taskStateLabel(state: RestoreTask["state"]): string {
	const labels: Record<RestoreTask["state"], string> = {
		Created: "正在创建",
		Queued: "排队中",
		Running: "正在恢复",
		WaitingForUser: "等待你处理",
		Retrying: "正在重试",
		Succeeded: "恢复完成",
		PartialSucceeded: "部分完成",
		Failed: "恢复失败",
		Cancelled: "已取消",
	};
	return labels[state];
}

function historyKindLabel(kind: string): string {
	if (kind === "NamedVersion") return "命名版本";
	if (kind === "Restore") return "恢复记录";
	return "检查点";
}

export function HistoryPanel({
	resourceId,
	journalSeq,
	onRestored,
}: {
	resourceId: string;
	journalSeq: number;
	onRestored?(): Promise<void>;
}) {
	const cache = useQueryClient();
	const navigate = useNavigate();
	const [label, setLabel] = useState("");
	const [restoreTaskId, setRestoreTaskId] = useState("");
	const lastReloadedTaskId = useRef("");
	const history = useQuery({
		queryKey: ["history", resourceId],
		queryFn: () => client.listHistory(resourceId),
	});
	const saveVersion = useMutation({
		mutationFn: () =>
			client.createNamedVersion(resourceId, label.trim(), journalSeq),
		onSuccess: async () => {
			setLabel("");
			await cache.invalidateQueries({ queryKey: ["history", resourceId] });
		},
	});
	const restoreVersion = useMutation({
		mutationFn: (baseJournalSeq: number) =>
			client.createVersionRestoreTask(
				resourceId,
				baseJournalSeq,
				crypto.randomUUID(),
			),
		onSuccess: (result) => {
			setRestoreTaskId(result.taskId);
		},
	});
	const restoreTask = useQuery({
		queryKey: ["task", restoreTaskId],
		queryFn: () => client.getTask(restoreTaskId),
		enabled: !!restoreTaskId,
		refetchInterval: (query) =>
			query.state.data && activeTaskStates.has(query.state.data.task.state)
				? 1_500
				: false,
	});
	const task = restoreTask.data?.task;
	const restoreInProgress = task ? activeTaskStates.has(task.state) : false;

	useEffect(() => {
		if (
			task?.state !== "Succeeded" ||
			lastReloadedTaskId.current === task.taskId
		)
			return;
		lastReloadedTaskId.current = task.taskId;
		void cache.invalidateQueries({ queryKey: ["history", resourceId] });
		void onRestored?.();
	}, [cache, onRestored, resourceId, task]);

	return (
		<section className="drawer-content" aria-label="文档历史">
			<form
				className="version-composer"
				onSubmit={(event) => {
					event.preventDefault();
					if (label.trim() && journalSeq > 0) saveVersion.mutate();
				}}
			>
				<input
					value={label}
					onChange={(event) => setLabel(event.target.value)}
					placeholder="为当前版本命名"
					aria-label="版本名称"
				/>
				<button
					type="submit"
					disabled={!label.trim() || journalSeq < 1 || saveVersion.isPending}
				>
					保存版本
				</button>
			</form>
			{history.isLoading && <p className="feature-muted">正在载入历史…</p>}
			{history.isError && (
				<p className="feature-error" role="alert">
					历史记录暂时不可用。
				</p>
			)}
			{saveVersion.isError && (
				<p className="feature-error" role="alert">
					版本创建失败，请重试。
				</p>
			)}
			{restoreVersion.isError && (
				<p className="feature-error" role="alert">
					版本恢复任务创建失败，请重试。
				</p>
			)}
			{restoreTaskId && (
				<p className="feature-muted" role="status" aria-live="polite">
					{restoreTask.isError
						? "无法获取恢复进度。"
						: task
							? `${taskStateLabel(task.state)}${task.stage ? ` · 阶段：${task.stage}` : ""}${typeof task.percentage === "number" ? ` · ${Math.round(task.percentage)}%` : ""}`
							: "正在读取恢复任务…"}{" "}
					<button type="button" onClick={() => navigate("/tasks")}>
						打开任务中心
					</button>
					{restoreTask.isError && (
						<button type="button" onClick={() => void restoreTask.refetch()}>
							重试查询
						</button>
					)}
				</p>
			)}
			{history.data?.items.map((item) => (
				<article className="history-card" key={`${item.seq}-${item.kind}`}>
					<div className="history-card-copy">
						<div className="history-card-title">
							<strong>{item.label ?? historyKindLabel(item.kind)}</strong>
							<span className="history-sequence">
								{item.seq === journalSeq ? "当前" : `#${item.seq}`}
							</span>
						</div>
						<small>{formatConsoleDate(item.occurredAt)}</small>
					</div>
					<button
						type="button"
						className="history-restore-button"
						disabled={
							restoreVersion.isPending || restoreInProgress || item.seq < 1
						}
						onClick={() => restoreVersion.mutate(item.seq)}
					>
						{restoreVersion.isPending ? "正在提交…" : "恢复到此版本"}
					</button>
				</article>
			))}
			{history.data?.items.length === 0 && (
				<p className="feature-muted">还没有版本记录。</p>
			)}
		</section>
	);
}
