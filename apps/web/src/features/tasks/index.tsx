import { DomApiError } from "@dom/client-sdk";
import {
	useInfiniteQuery,
	useMutation,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { client } from "../../shared/api/client";

type Task = Awaited<ReturnType<typeof client.listTasks>>["tasks"][number];
const taskPageSize = 50;

function retryStorageKey(accountId: string, taskId: string): string {
	return `dom:task-center:retry:${encodeURIComponent(accountId)}:${encodeURIComponent(taskId)}`;
}

const uncertainRetryStatuses = new Set([408, 425, 429]);

function isDefinitiveRetryRejection(error: DomApiError): boolean {
	return (
		error.status >= 400 &&
		error.status < 500 &&
		!uncertainRetryStatuses.has(error.status) &&
		!error.retryable
	);
}

const activeStates = new Set<Task["state"]>([
	"Created",
	"Queued",
	"Running",
	"WaitingForUser",
	"Retrying",
]);

const stateLabels: Record<Task["state"], string> = {
	Created: "正在创建",
	Queued: "排队中",
	Running: "处理中",
	WaitingForUser: "等待你处理",
	Retrying: "正在重试",
	Succeeded: "已完成",
	PartialSucceeded: "部分完成",
	Failed: "失败",
	Cancelled: "已取消",
};

const taskLabels: Record<string, string> = {
	"ai.generate": "AI 处理",
	"export.project": "导出项目",
	"history.restore": "恢复历史版本",
	"import.project": "导入项目",
	"lifecycle.purge": "清理工作区",
	"resource.checkpoint": "保存文档检查点",
	"resource.purge": "清理文档",
	"webhook.deliver": "发送 Webhook",
};

function taskTitle(task: Task): string {
	return taskLabels[task.taskType] ?? task.taskType.replace(/[._-]+/g, " ");
}

function taskProgress(task: Task): number | null {
	if (task.percentage !== null) return task.percentage;
	if (task.current !== null && task.total !== null && task.total > 0) {
		return (task.current / task.total) * 100;
	}
	return null;
}

function taskTime(task: Task): string {
	const value =
		task.finishedAt ?? task.updatedAt ?? task.startedAt ?? task.queuedAt;
	if (!value || Number.isNaN(Date.parse(value))) return "时间暂不可用";
	return new Intl.DateTimeFormat("zh-CN", {
		month: "short",
		day: "numeric",
		hour: "2-digit",
		minute: "2-digit",
	}).format(new Date(value));
}

function TaskCard({
	task,
	onCancel,
	onRetry,
	busy,
}: {
	task: Task;
	onCancel(): void;
	onRetry(): void;
	busy: boolean;
}) {
	const active = activeStates.has(task.state);
	const percentage = taskProgress(task);
	return (
		<article
			className="task-card"
			data-testid="task-card"
			data-task-id={task.taskId}
		>
			<div className="task-card-top">
				<div className="task-card-title-group">
					<h2>{taskTitle(task)}</h2>
					<time className="task-timestamp">{taskTime(task)}</time>
				</div>
				<span
					className={`task-state-badge task-state-${task.state.toLowerCase()}`}
				>
					{stateLabels[task.state]}
				</span>
			</div>
			<div className="task-card-meta">
				<span className="task-stage">
					{task.stage
						? `阶段 · ${task.stage.replace(/[._-]+/g, " ")}`
						: active
							? "正在处理"
							: "任务已结束"}
				</span>
				{task.current !== null && task.total !== null && (
					<span>
						{task.current.toLocaleString("zh-CN")} /{" "}
						{task.total.toLocaleString("zh-CN")}
					</span>
				)}
			</div>
			<div className="task-progress-wrap">
				<progress
					className="task-progress"
					max={100}
					value={
						percentage === null
							? undefined
							: Math.min(100, Math.max(0, percentage))
					}
					aria-label={`${taskTitle(task)}进度`}
				/>
				<span className="task-progress-label">
					{percentage === null
						? active
							? "进度尚未上报"
							: "无进度数据"
						: `${Math.round(percentage)}%`}
				</span>
			</div>
			<div className="task-card-footer">
				{task.state === "Failed" && (
					<p className="task-failure-code">
						{task.failureCode ? (
							<>
								失败代码 <code>{task.failureCode}</code>
							</>
						) : (
							"任务失败，服务未返回错误代码。"
						)}
					</p>
				)}
				<div className="task-card-actions">
					{active && (
						<button
							type="button"
							className="task-secondary-button"
							disabled={busy || task.cancelRequestedAt !== null}
							onClick={onCancel}
						>
							{task.cancelRequestedAt ? "正在请求取消" : "取消任务"}
						</button>
					)}
					{task.state === "Failed" && (
						<button
							type="button"
							className="task-primary-button"
							disabled={busy}
							onClick={onRetry}
						>
							{busy ? "正在重试…" : "重试任务"}
						</button>
					)}
				</div>
			</div>
		</article>
	);
}

export function TaskCenterPage() {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const [retryStorageError, setRetryStorageError] = useState<string | null>(
		null,
	);
	const account = useQuery({
		queryKey: ["account"],
		queryFn: () => client.me(),
	});
	const tasks = useInfiniteQuery({
		queryKey: ["tasks"],
		initialPageParam: 0,
		queryFn: ({ pageParam }) =>
			client.listTasks({ limit: taskPageSize, offset: pageParam }),
		getNextPageParam: (lastPage) =>
			lastPage.tasks.length < lastPage.limit
				? undefined
				: lastPage.offset + lastPage.limit,
		refetchInterval: (query) =>
			query.state.data?.pages.some((page) =>
				page.tasks.some((task) => activeStates.has(task.state)),
			)
				? 4_000
				: 12_000,
	});
	const mutation = useMutation({
		mutationFn: async ({
			task,
			action,
			accountId,
		}: {
			task: Task;
			action: "cancel" | "retry";
			accountId: string | null;
		}) => {
			if (action === "cancel") return client.cancelTask(task.taskId);
			if (!accountId) {
				throw new Error("当前账号信息尚未就绪，无法安全发起重试。请稍后再试。");
			}
			const key = retryStorageKey(accountId, task.taskId);
			let idempotencyKey: string | null;
			try {
				idempotencyKey = window.sessionStorage.getItem(key);
			} catch {
				throw new Error(
					"无法读取浏览器会话中的重试记录，本次重试未发送。请允许此站点使用会话存储后再试。",
				);
			}
			if (!idempotencyKey) {
				idempotencyKey = crypto.randomUUID();
				try {
					window.sessionStorage.setItem(key, idempotencyKey);
				} catch {
					throw new Error(
						"无法保存浏览器会话中的重试记录，本次重试未发送。请允许此站点使用会话存储后再试。",
					);
				}
			}
			return client.retryTask(task.taskId, idempotencyKey);
		},
		onSuccess: async (_result, variables) => {
			if (variables.action === "retry" && variables.accountId) {
				try {
					window.sessionStorage.removeItem(
						retryStorageKey(variables.accountId, variables.task.taskId),
					);
				} catch {
					setRetryStorageError(
						"重试已提交，但无法清除浏览器中的待处理记录。再次重试仍会复用原请求，请先检查此站点的会话存储权限。",
					);
				}
			}
			await queryClient.invalidateQueries({ queryKey: ["tasks"] });
		},
		onError: (error, variables) => {
			if (
				variables.action === "retry" &&
				variables.accountId &&
				error instanceof DomApiError &&
				isDefinitiveRetryRejection(error)
			) {
				try {
					window.sessionStorage.removeItem(
						retryStorageKey(variables.accountId, variables.task.taskId),
					);
				} catch {
					setRetryStorageError(
						"服务器已拒绝这次重试，但无法清除浏览器中的重试记录。请检查此站点的会话存储权限后再操作。",
					);
				}
			}
		},
	});
	if (account.isSuccess && account.data === null)
		return <Navigate to="/login" replace />;
	const items = tasks.data?.pages.flatMap((page) => page.tasks) ?? [];
	const activeCount = items.filter((task) =>
		activeStates.has(task.state),
	).length;
	const completedCount = items.filter(
		(task) => task.state === "Succeeded" || task.state === "PartialSucceeded",
	).length;
	const failedCount = items.filter((task) => task.state === "Failed").length;
	return (
		<div className="app-stage console-shell task-center-shell">
			<header className="console-topbar task-center-topbar">
				<button
					type="button"
					className="task-back-button"
					onClick={() => navigate("/workspace")}
				>
					<span aria-hidden="true">←</span> 工作区
				</button>
				<span className="task-account-label">
					{account.data?.primaryEmail ?? ""}
				</span>
			</header>
			<main className="console-main task-center-main">
				<div className="task-center-content">
					<div className="task-center-heading">
						<p className="task-center-eyebrow">工作进度</p>
						<div className="task-center-title-row">
							<h1>任务中心</h1>
							<button
								type="button"
								className="task-refresh-button"
								onClick={() => void tasks.refetch()}
							>
								刷新
							</button>
						</div>
						<p className="task-center-subtitle">
							查看导入、导出、恢复和其他后台操作的最新进度。
						</p>
					</div>
					<p
						className="task-center-live-status"
						role="status"
						aria-live="polite"
						data-testid="task-center-status"
					>
						{tasks.isFetching
							? "正在同步任务状态…"
							: tasks.isError
								? "无法同步最新任务状态"
								: "任务状态已同步"}
					</p>
					{tasks.isError && !tasks.isFetchNextPageError && (
						<div className="task-center-alert" role="alert">
							{tasks.data
								? "最新任务状态暂时无法同步，已保留当前列表。"
								: "任务暂时无法加载。请检查网络后重试。"}
							<button
								type="button"
								className="task-primary-button"
								onClick={() => void tasks.refetch()}
							>
								重新加载
							</button>
						</div>
					)}
					{mutation.isError && (
						<div className="task-center-alert" role="alert">
							{mutation.error instanceof Error
								? mutation.error.message
								: "任务操作失败，请重试。"}
						</div>
					)}
					{retryStorageError && (
						<div className="task-center-alert" role="alert">
							{retryStorageError}
						</div>
					)}
					<section className="task-summary-grid" aria-label="任务数量摘要">
						<div className="task-summary-card task-summary-active">
							<strong>{activeCount}</strong>
							<span>进行中</span>
						</div>
						<div className="task-summary-card task-summary-complete">
							<strong>{completedCount}</strong>
							<span>已完成</span>
						</div>
						<div className="task-summary-card task-summary-failed">
							<strong>{failedCount}</strong>
							<span>失败</span>
						</div>
					</section>
					<section
						className="task-list"
						data-testid="task-center-list"
						aria-label="任务列表"
						aria-busy={tasks.isLoading}
					>
						{tasks.isLoading ? (
							<div className="task-center-state" aria-busy="true">
								正在加载任务…
							</div>
						) : tasks.isError && !tasks.data ? (
							<div className="task-center-state task-center-error-state">
								任务暂时无法加载。请检查网络后重试。
							</div>
						) : items.length === 0 ? (
							<div className="task-center-state task-center-empty-state">
								<div className="task-empty-icon" aria-hidden="true">
									◷
								</div>
								<h2>目前没有任务</h2>
								<p>有长时间运行的操作时，它们会显示在这里。</p>
							</div>
						) : (
							items.map((task) => (
								<TaskCard
									key={task.taskId}
									task={task}
									busy={
										mutation.isPending &&
										mutation.variables?.task.taskId === task.taskId
									}
									onCancel={() =>
										mutation.mutate({
											task,
											action: "cancel",
											accountId: account.data?.accountId ?? null,
										})
									}
									onRetry={() => {
										setRetryStorageError(null);
										mutation.mutate({
											task,
											action: "retry",
											accountId: account.data?.accountId ?? null,
										});
									}}
								/>
							))
						)}
						{tasks.isFetchNextPageError && (
							<div className="task-center-alert" role="alert">
								更多任务暂时无法加载，已保留当前列表。
							</div>
						)}
						{tasks.hasNextPage && (
							<button
								type="button"
								className="task-secondary-button task-load-more"
								disabled={tasks.isFetchingNextPage}
								aria-busy={tasks.isFetchingNextPage}
								onClick={() => void tasks.fetchNextPage()}
							>
								{tasks.isFetchingNextPage
									? "正在加载更多…"
									: tasks.isFetchNextPageError
										? "重试加载更多"
										: "加载更多"}
							</button>
						)}
					</section>
				</div>
			</main>
		</div>
	);
}
