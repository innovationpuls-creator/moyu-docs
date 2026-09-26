import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { client } from "../../shared/api/client";
import { ConsoleIcon } from "../../shared/ui/console-icons";
import { formatConsoleDate } from "../../shared/ui/date";

function recordOf(payload: unknown): Record<string, unknown> {
	if (typeof payload !== "object" || payload === null) return {};
	return payload as Record<string, unknown>;
}

function stringField(payload: unknown, field: string): string | null {
	const value = recordOf(payload)[field];
	return typeof value === "string" && value.length > 0 ? value : null;
}

function notificationTitle(kind: string): string {
	if (kind === "comment.mention") return "有人在评论中提到了你";
	if (kind === "workspace.invitation.created") return "收到工作区邀请";
	if (kind === "workspace.invitation.accepted") return "工作区邀请已被接受";
	return "一条新通知";
}

export function NotificationCenter({
	onOpenResource,
}: {
	onOpenResource(resourceId: string): void;
}) {
	const cache = useQueryClient();
	const navigate = useNavigate();
	const [open, setOpen] = useState(false);
	const notifications = useQuery({
		queryKey: ["notifications"],
		queryFn: () => client.listNotifications(),
		refetchInterval: 30_000,
		refetchIntervalInBackground: false,
		refetchOnWindowFocus: true,
	});
	const readOne = useMutation({
		mutationFn: (notificationId: string) =>
			client.markNotificationRead(notificationId),
		onSuccess: () => cache.invalidateQueries({ queryKey: ["notifications"] }),
	});
	const readAll = useMutation({
		mutationFn: () => client.markAllNotificationsRead(),
		onSuccess: () => cache.invalidateQueries({ queryKey: ["notifications"] }),
	});
	const acceptInvitation = useMutation({
		mutationFn: (invitationId: string) =>
			client.acceptWorkspaceInvitationById(invitationId),
		onSuccess: async (result) => {
			await Promise.all([
				cache.invalidateQueries({ queryKey: ["notifications"] }),
				cache.invalidateQueries({ queryKey: ["workspaces"] }),
			]);
			setOpen(false);
			navigate(
				`/workspace?workspaceId=${encodeURIComponent(result.workspaceId)}`,
			);
		},
	});
	const result = notifications.data;
	const items = result?.items ?? [];
	return (
		<div className="console-menu-anchor notification-anchor">
			<button
				type="button"
				className="icon-btn-quiet"
				data-testid="console-notifications"
				aria-label="通知"
				aria-expanded={open}
				onClick={() => setOpen((value) => !value)}
			>
				<ConsoleIcon name="bell" size={18} />
				{(result?.unreadCount ?? 0) > 0 && (
					<span className="bell-badge-dot" data-testid="notifications-unread">
						{result?.unreadCount}
					</span>
				)}
			</button>
			{open && (
				<section
					className="console-dropdown notification-dropdown"
					role="dialog"
					aria-label="通知"
				>
					<header className="notification-header">
						<strong>通知</strong>
						<button
							type="button"
							disabled={!result?.unreadCount || readAll.isPending}
							onClick={() => readAll.mutate()}
						>
							全部已读
						</button>
					</header>
					{notifications.isLoading && (
						<p className="notification-empty">正在载入…</p>
					)}
					{notifications.isError && (
						<p className="notification-empty" role="alert">
							通知暂时不可用。
						</p>
					)}
					{!notifications.isLoading && !items.length && (
						<p className="notification-empty">暂时没有通知。</p>
					)}
					<ul className="notification-list">
						{items.map((item) => {
							const payload = recordOf(item.payload);
							const workspaceName = stringField(payload, "workspaceName");
							const inviterEmail = stringField(payload, "inviterEmail");
							const inviteeEmail = stringField(payload, "inviteeEmail");
							const invitationId = item.targetRef?.invitationId;
							const targetResourceId = item.targetRef?.resourceId;
							const resourceId =
								typeof targetResourceId === "string"
									? targetResourceId
									: stringField(payload, "resourceId");
							const workspaceId = stringField(payload, "workspaceId");
							const excerpt =
								item.kind === "workspace.invitation.created"
									? `${inviterEmail ?? "工作区成员"} 邀请你加入「${workspaceName ?? "工作区"}」`
									: item.kind === "workspace.invitation.accepted"
										? `${inviteeEmail ?? "受邀成员"} 已加入「${workspaceName ?? "工作区"}」`
										: stringField(payload, "excerpt");
							return (
								<li
									key={item.notificationId}
									className={item.readAt ? "read" : "unread"}
								>
									<button
										type="button"
										onClick={() => {
											if (!item.readAt) readOne.mutate(item.notificationId);
											if (resourceId) {
												setOpen(false);
												onOpenResource(resourceId);
											} else if (
												workspaceId &&
												item.kind === "workspace.invitation.accepted"
											) {
												setOpen(false);
												navigate(
													`/workspace?workspaceId=${encodeURIComponent(workspaceId)}`,
												);
											}
										}}
									>
										<span className="notification-dot" aria-hidden="true" />
										<span>
											<strong>{notificationTitle(item.kind)}</strong>
											{excerpt && (
												<small className="notification-excerpt">
													{excerpt}
												</small>
											)}
											<small>{formatConsoleDate(item.createdAt)}</small>
										</span>
									</button>
									{item.kind === "workspace.invitation.created" &&
										typeof invitationId === "string" && (
											<button
												className="notification-accept"
												type="button"
												disabled={acceptInvitation.isPending}
												onClick={() => acceptInvitation.mutate(invitationId)}
											>
												{acceptInvitation.isPending ? "正在加入…" : "接受邀请"}
											</button>
										)}
								</li>
							);
						})}
					</ul>
					{acceptInvitation.error && (
						<p className="notification-empty" role="alert">
							接受邀请失败：
							{acceptInvitation.error instanceof Error
								? acceptInvitation.error.message
								: "请稍后重试。"}
						</p>
					)}
				</section>
			)}
		</div>
	);
}
