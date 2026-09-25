import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../../shared/api/client";
import { ConsoleIcon } from "../../shared/ui/console-icons";
import { formatConsoleDate } from "../../shared/ui/date";

function notificationTarget(payload: unknown): string | null {
	if (typeof payload !== "object" || payload === null) return null;
	const resourceId = (payload as Record<string, unknown>).resourceId;
	return typeof resourceId === "string" ? resourceId : null;
}

function notificationExcerpt(payload: unknown): string | null {
	if (typeof payload !== "object" || payload === null) return null;
	const excerpt = (payload as Record<string, unknown>).excerpt;
	return typeof excerpt === "string" && excerpt.length > 0 ? excerpt : null;
}

function notificationTitle(kind: string): string {
	if (kind === "comment.mention") return "有人在评论中提到了你";
	return "一条新通知";
}

export function NotificationCenter({
	onOpenResource,
}: {
	onOpenResource(resourceId: string): void;
}) {
	const cache = useQueryClient();
	const [open, setOpen] = useState(false);
	const notifications = useQuery({
		queryKey: ["notifications"],
		queryFn: () => client.listNotifications(),
		enabled: open,
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
							const target = notificationTarget(item.payload);
							const excerpt = notificationExcerpt(item.payload);
							return (
								<li
									key={item.notificationId}
									className={item.readAt ? "read" : "unread"}
								>
									<button
										type="button"
										onClick={() => {
											if (!item.readAt) readOne.mutate(item.notificationId);
											if (target) {
												setOpen(false);
												onOpenResource(target);
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
								</li>
							);
						})}
					</ul>
				</section>
			)}
		</div>
	);
}
