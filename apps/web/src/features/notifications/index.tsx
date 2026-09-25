import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../../shared/api/client";

function notificationTarget(payload: unknown): string | null {
	if (typeof payload !== "object" || payload === null) return null;
	const resourceId = (payload as Record<string, unknown>).resourceId;
	return typeof resourceId === "string" ? resourceId : null;
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
				<svg
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					strokeWidth="1.8"
					strokeLinecap="round"
					strokeLinejoin="round"
					aria-hidden="true"
				>
					<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
				</svg>
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
											<strong>{item.kind}</strong>
											<small>
												{item.createdAt
													? new Date(item.createdAt).toLocaleString()
													: ""}
											</small>
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
