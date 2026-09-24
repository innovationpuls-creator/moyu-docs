/**
 * /workspace page: post-auth entry. Reads the current account via
 * DomClient.me(); if the session is no longer valid the page redirects to
 * /login (refresh/restart recovery — FR-AUTH-021). Shows the account email and
 * a logout button (FR-AUTH-020).
 */

import { DomClient } from "@dom/client-sdk";

import { navigate } from "../main";

export async function renderWorkspacePage(app: HTMLElement): Promise<void> {
	console.error("[dom-web] renderWorkspacePage v2");
	const client = new DomClient();
	const account = await client.me();
	if (account === null) {
		navigate("/login");
		return;
	}
	app.replaceChildren();

	const heading = document.createElement("h1");
	heading.textContent = "工作台";

	const email = document.createElement("p");
	email.dataset.testid = "workspace-email";
	email.textContent = account.primaryEmail;

	const list = document.createElement("ul");
	list.dataset.testid = "workspace-list";
	const workspaces = await client.listWorkspaces();
	const firstWorkspaceId: string | null =
		workspaces.workspaces[0]?.workspaceId ?? null;
	if (workspaces.workspaces.length === 0) {
		const empty = document.createElement("li");
		empty.dataset.testid = "workspace-empty";
		empty.textContent = "暂无工作区";
		list.append(empty);
	} else {
		const tree = document.createElement("div");
		tree.dataset.testid = "navigation-tree";
		// Event delegation: one listener per level; re-renders never lose
		// handlers (robust to replaceChildren + async loads).
		for (const ws of workspaces.workspaces) {
			const row = document.createElement("li");
			row.dataset.testid = "workspace-row";
			row.textContent = `${ws.name} (${ws.membershipKind})`;
			const projects = document.createElement("ul");
			projects.dataset.testid = "project-list";
			row.addEventListener("click", async () => {
				try {
					const result = await client.listProjects(ws.workspaceId);
					projects.replaceChildren();
					for (const project of result.items) {
						const item = document.createElement("li");
						item.dataset.testid = "project-row";
						item.textContent = project.name;
						const resources = document.createElement("ul");
						resources.dataset.testid = "resource-list";
						item.addEventListener("click", async (event) => {
							event.stopPropagation();
							try {
								const list = await client.listResources(project.projectId);
								resources.replaceChildren();
								for (const res of list.items) {
									if (res.lifecycle !== "Active") continue;
									const resourceRow = document.createElement("li");
									resourceRow.dataset.testid = "resource-row";
									resourceRow.textContent = res.name;
									resourceRow.addEventListener("click", (event) => {
										event.stopPropagation();
										navigate(`/editor?resource=${res.resourceId}`);
									});
									resources.append(resourceRow);
								}
							} catch {
								resources.replaceChildren();
							}
						});
						item.append(resources);
						projects.append(item);
					}
				} catch {
					projects.replaceChildren();
				}
			});
			row.append(projects);
			tree.append(row);
		}
		app.append(tree);
	}
	app.append(list);
	app.append(list);

	const editorLink = document.createElement("a");
	editorLink.href = "/editor";
	editorLink.textContent = "进入编辑器";
	editorLink.dataset.testid = "editor-link";

	const logout = document.createElement("button");
	logout.type = "button";
	logout.textContent = "退出登录";
	logout.dataset.testid = "logout-button";
	logout.addEventListener("click", () => {
		void (async () => {
			await client.logout();
			navigate("/login");
		})();
	});

	// Search (arch 11 §3): workspace search + per-account history.
	const searchSection = document.createElement("section");
	searchSection.dataset.testid = "search-panel";
	const searchInput = document.createElement("input");
	searchInput.dataset.testid = "search-input";
	searchInput.placeholder = "搜索工作区…";
	const searchRun = document.createElement("button");
	searchRun.type = "button";
	searchRun.dataset.testid = "search-run";
	searchRun.textContent = "搜索";
	const searchResults = document.createElement("ul");
	searchResults.dataset.testid = "search-results";
	const searchHistoryList = document.createElement("ul");
	searchHistoryList.dataset.testid = "search-history";
	searchRun.addEventListener("click", (event) => {
		event.stopPropagation();
		void (async () => {
			try {
				const { DomClient } = await import("@dom/client-sdk");
				if (!firstWorkspaceId) {
					searchResults.replaceChildren();
					return;
				}
				const result = await new DomClient().searchWorkspace(
					firstWorkspaceId,
					searchInput.value,
				);
				searchResults.replaceChildren();
				if (result.items.length === 0) {
					const empty = document.createElement("li");
					empty.dataset.testid = "search-empty";
					empty.textContent = "无结果";
					searchResults.append(empty);
				} else {
					for (const item of result.items) {
						const row = document.createElement("li");
						row.dataset.testid = "search-result-row";
						row.textContent = `${item.name}${item.snippet ? ` — ${item.snippet}` : ""}`;
						searchResults.append(row);
					}
				}
				const history = await new DomClient().searchHistory();
				searchHistoryList.replaceChildren();
				for (const entry of history.items) {
					const row = document.createElement("li");
					row.textContent = entry.query;
					searchHistoryList.append(row);
				}
			} catch {
				searchResults.replaceChildren();
			}
		})();
	});
	const clearHistory = document.createElement("button");
	clearHistory.type = "button";
	clearHistory.dataset.testid = "search-history-clear";
	clearHistory.textContent = "清空历史";
	clearHistory.addEventListener("click", (event) => {
		event.stopPropagation();
		void (async () => {
			try {
				const { DomClient } = await import("@dom/client-sdk");
				await new DomClient().clearSearchHistory();
				searchHistoryList.replaceChildren();
			} catch {
				// best-effort clear; the API envelope surfaces on failure
			}
		})();
	});
	searchSection.append(
		searchInput,
		searchRun,
		searchResults,
		searchHistoryList,
		clearHistory,
	);

	// Notifications (arch 17 §17-§19): in-app list + mark-all-read.
	const notificationsSection = document.createElement("section");
	notificationsSection.dataset.testid = "notifications-panel";
	const notificationsHeading = document.createElement("h3");
	notificationsHeading.textContent = "通知";
	const unreadBadge = document.createElement("span");
	unreadBadge.dataset.testid = "notifications-unread";
	unreadBadge.textContent = "0";
	const notificationsList = document.createElement("ul");
	notificationsList.dataset.testid = "notifications-list";
	const renderNotifications = async (): Promise<void> => {
		try {
			const { DomClient } = await import("@dom/client-sdk");
			const result = await new DomClient().listNotifications();
			unreadBadge.textContent = String(result.unreadCount);
			notificationsList.replaceChildren();
			if (result.items.length === 0) {
				const empty = document.createElement("li");
				empty.textContent = "暂无通知";
				notificationsList.append(empty);
				return;
			}
			for (const notification of result.items) {
				const row = document.createElement("li");
				row.dataset.testid = "notification-row";
				const payload = notification.payload as {
					excerpt?: string;
					resourceId?: string;
				} | null;
				row.textContent = `${notification.kind}${payload?.excerpt ? `: ${payload.excerpt}` : ""}`;
				row.style.cursor = "pointer";
				row.addEventListener("click", (event) => {
					event.stopPropagation();
					void (async () => {
						try {
							const { DomClient } = await import("@dom/client-sdk");
							await new DomClient().markNotificationRead(
								notification.notificationId,
							);
						} catch {
							// best-effort read-marking; the jump still happens
						}
						if (payload?.resourceId) {
							location.assign(`/editor?resource=${payload.resourceId}`);
						}
					})();
				});
				notificationsList.append(row);
			}
		} catch {
			notificationsList.replaceChildren();
		}
	};
	void renderNotifications();
	const markAllRead = document.createElement("button");
	markAllRead.type = "button";
	markAllRead.dataset.testid = "notifications-read-all";
	markAllRead.textContent = "全部已读";
	markAllRead.addEventListener("click", (event) => {
		event.stopPropagation();
		void (async () => {
			try {
				const { DomClient } = await import("@dom/client-sdk");
				await new DomClient().markAllNotificationsRead();
				await renderNotifications();
			} catch {
				// best-effort UI; the API error envelope is already surfaced
			}
		})();
	});
	notificationsSection.append(
		notificationsHeading,
		unreadBadge,
		notificationsList,
		markAllRead,
	);

	app.append(
		heading,
		email,
		editorLink,
		logout,
		searchSection,
		notificationsSection,
	);
}
