/**
 * /workspace 管理台页（B 组 Step 5 · 生产实现）。
 *
 * 结构：顶栏收纳（工作区切换 / Cmd+K 搜索入口 / 通知铃铛 / 账号菜单）
 *      + 左栏组织树（工作区 → 项目 → 资源，展开/折叠）
 *      + 主区（面包屑 + 上下文新建 + 资源列表 + 空态矩阵 + 回收站视图）。
 *
 * 数据全部经 @dom/client-sdk 读取（feature 代码不直接 fetch）；后端契约
 * 字段：workspace(name/membershipKind/lifecycle)、project(name)、
 * resource(name/resourceType/lifecycle)、search({resourceId,name,snippet})、
 * notification(kind/payload)。
 *
 * 兼容既有 E2E 契约：workspace-email / workspace-list / workspace-empty /
 * navigation-tree / workspace-row / project-list / project-row / resource-list /
 * resource-row / editor-link / logout-button / search-* / notifications-*。
 */

import { DomApiError, DomClient } from "@dom/client-sdk";

import {
	createPatchwork,
	emptyStateCard,
	illustrationNoProjects,
	illustrationNoResources,
	illustrationNoWorkspace,
	makeDropdown,
	resourceTypeIcon,
	svgIcon,
} from "../components/console";
import { navigate } from "../main";

type ResourceType = "document" | "code" | "markdown" | "text";

interface ProjectRef {
	projectId: string;
	name: string;
}

interface ResourceRef {
	resourceId: string;
	name: string;
	resourceType: ResourceType;
	lifecycle: "Active" | "Trashed" | "Purging" | "Purged";
}

interface NotificationItem {
	notificationId: string;
	kind: string;
	payload: { excerpt?: string; resourceId?: string } | null;
}

const RESOURCE_TYPE_LABEL: Record<ResourceType, string> = {
	document: "document",
	code: "code",
	markdown: "markdown",
	text: "text",
};

export async function renderWorkspacePage(app: HTMLElement): Promise<void> {
	const client = new DomClient();
	const account = await client.me();
	if (account === null) {
		navigate("/login");
		return;
	}
	app.replaceChildren();
	app.append(createPatchwork());

	/* ---------------- 状态 ---------------- */
	let workspaces: Array<{
		workspaceId: string;
		name: string;
		membershipKind: string;
	}> = [];
	let currentWorkspaceId: string | null = null;
	let currentWorkspaceName = "";
	let currentProject: ProjectRef | null = null;

	/* ---------------- 顶栏 ---------------- */
	const shell = document.createElement("div");
	shell.className = "console-shell";
	shell.dataset.testid = "console-shell";
	const topbar = document.createElement("header");
	topbar.className = "console-topbar";

	const topbarLeft = document.createElement("div");
	topbarLeft.className = "topbar-left";
	const topbarRight = document.createElement("div");
	topbarRight.className = "topbar-right";

	// 工作区切换器
	const wsAnchor = document.createElement("div");
	wsAnchor.style.position = "relative";
	const wsBtn = document.createElement("button");
	wsBtn.type = "button";
	wsBtn.className = "ws-switcher-btn";
	wsBtn.dataset.testid = "console-workspace-switcher";
	const wsBadge = document.createElement("span");
	wsBadge.className = "ws-badge";
	wsBadge.append(svgIcon("workspace", 14));
	const wsName = document.createElement("span");
	wsName.className = "ws-name";
	wsName.id = "currentWsName";
	wsName.textContent = "加载中…";
	const wsRole = document.createElement("span");
	wsRole.className = "ws-role-pill";
	wsRole.id = "currentWsRole";
	wsBtn.append(wsBadge, wsName, wsRole, svgIcon("chevron", 12));
	const wsDropdown = makeDropdown();
	wsBtn.addEventListener("click", () => toggleDropdown("wsDropdown"));
	wsAnchor.append(wsBtn, wsDropdown);

	// 搜索入口（Cmd+K）
	const searchTrigger = document.createElement("button");
	searchTrigger.type = "button";
	searchTrigger.className = "search-trigger-bar";
	searchTrigger.dataset.testid = "console-search-trigger";
	searchTrigger.append(svgIcon("search", 15));
	const searchLabel = document.createElement("span");
	searchLabel.textContent = "搜索工作区资源…";
	searchTrigger.append(searchLabel);
	const kbd = document.createElement("span");
	kbd.className = "search-shortcut-pill";
	kbd.textContent = "Cmd K";
	searchTrigger.append(kbd);
	searchTrigger.addEventListener("click", () => openPalette());

	// 手机端侧栏汉堡
	const hamburger = document.createElement("button");
	hamburger.type = "button";
	hamburger.className = "mobile-sidebar-toggle";
	hamburger.dataset.testid = "console-sidebar-toggle";
	hamburger.append(svgIcon("panel", 18));
	hamburger.addEventListener("click", () => toggleMobileSidebar());
	topbarLeft.append(hamburger, wsAnchor, searchTrigger);

	// 通知铃铛
	const notifAnchor = document.createElement("div");
	notifAnchor.style.position = "relative";
	const notifBtn = document.createElement("button");
	notifBtn.type = "button";
	notifBtn.className = "icon-btn-quiet";
	notifBtn.dataset.testid = "console-notifications";
	notifBtn.title = "通知";
	notifBtn.append(svgIcon("bell", 18));
	const bellDot = document.createElement("span");
	bellDot.className = "bell-badge-dot";
	bellDot.dataset.testid = "notifications-unread";
	notifBtn.append(bellDot);
	const notifDropdown = makeDropdown(300);
	notifDropdown.dataset.testid = "notifications-panel";
	notifBtn.addEventListener("click", () => toggleDropdown("notifDropdown"));
	notifAnchor.append(notifBtn, notifDropdown);

	// 账号菜单
	const accountAnchor = document.createElement("div");
	accountAnchor.style.position = "relative";
	const accountBtn = document.createElement("button");
	accountBtn.type = "button";
	accountBtn.className = "account-menu-trigger";
	accountBtn.dataset.testid = "console-account-menu";
	const avatar = document.createElement("div");
	avatar.className = "user-avatar-circle";
	avatar.textContent = (account.primaryEmail[0] ?? "U").toUpperCase();
	const emailLabel = document.createElement("span");
	emailLabel.className = "account-email-label";
	emailLabel.textContent = account.primaryEmail;
	accountBtn.append(avatar, emailLabel, svgIcon("chevron", 12));
	const accountDropdown = makeDropdown();
	accountBtn.addEventListener("click", () => toggleDropdown("accountDropdown"));
	accountAnchor.append(accountBtn, accountDropdown);
	topbarRight.append(notifAnchor, accountAnchor);
	topbar.append(topbarLeft, topbarRight);

	/* ---------------- 主体 ---------------- */
	const body = document.createElement("div");
	body.className = "console-body";

	// 左栏：组织树
	const sidebar = document.createElement("aside");
	sidebar.className = "console-sidebar";
	sidebar.dataset.testid = "console-tree";
	const sidebarBackdrop = document.createElement("div");
	sidebarBackdrop.className = "console-sidebar-backdrop";
	sidebarBackdrop.addEventListener("click", () => closeMobileSidebar());

	const sectionTitle = document.createElement("div");
	sectionTitle.className = "sidebar-section-title";
	sectionTitle.textContent = "项目空间";
	const treeWrap = document.createElement("div");
	treeWrap.dataset.testid = "navigation-tree";
	const list = document.createElement("ul");
	list.dataset.testid = "workspace-list";
	list.className = "tree-node-list";
	treeWrap.append(list);
	sidebar.append(sectionTitle, treeWrap);

	// 快捷入口：编辑器
	const editorRow = document.createElement("button");
	editorRow.type = "button";
	editorRow.className = "tree-node-row";
	editorRow.dataset.testid = "editor-link";
	editorRow.append(svgIcon("document", 15));
	const editorRowLabel = document.createElement("span");
	editorRowLabel.textContent = "进入编辑器";
	editorRow.append(editorRowLabel);
	editorRow.addEventListener("click", () => navigate("/editor"));

	// 回收站
	const trashRow = document.createElement("button");
	trashRow.type = "button";
	trashRow.className = "sidebar-trash-row";
	trashRow.dataset.testid = "console-trash-row";
	trashRow.append(svgIcon("trash", 16));
	const trashLabel = document.createElement("span");
	trashLabel.textContent = "回收站";
	trashRow.append(trashLabel);
	trashRow.addEventListener("click", () => openTrashView());
	sidebar.append(editorRow, trashRow);

	// 主区
	const main = document.createElement("main");
	main.className = "console-main";
	main.dataset.testid = "console-main";

	const welcome = document.createElement("div");
	welcome.className = "console-welcome";
	const emailLine = document.createElement("p");
	emailLine.style.fontSize = "13px";
	emailLine.style.color = "var(--ink-muted)";
	const emailPrefix = document.createElement("span");
	emailPrefix.textContent = "登录为 ";
	const emailValue = document.createElement("span");
	emailValue.dataset.testid = "workspace-email";
	emailValue.textContent = account.primaryEmail;
	emailLine.append(emailPrefix, emailValue);
	welcome.append(emailLine);
	main.append(welcome);

	// 邮箱验证引导（PendingVerification 才出现）：注册后即登录进入工作台，
	// 但未验证账户创建不了工作区——前端必须给出显式引导与重发入口，
	// 而不是让用户撞 403 后无路可走（FR-AUTH 验证链的产品面）。
	const pendingVerification = account.accountStatus === "PendingVerification";
	let resendTimer: ReturnType<typeof setInterval> | undefined;
	if (pendingVerification) {
		const banner = document.createElement("div");
		banner.className = "verify-banner";
		banner.dataset.testid = "console-verify-banner";
		const iconWrap = document.createElement("div");
		iconWrap.className = "verify-icon";
		iconWrap.append(svgIcon("bell", 18));
		const copy = document.createElement("div");
		copy.className = "verify-copy";
		const title = document.createElement("div");
		title.className = "verify-title";
		title.textContent = "还差一步：去邮箱完成验证";
		const desc = document.createElement("div");
		desc.className = "verify-desc";
		desc.textContent =
			"验证后即可创建工作区并邀请协作者；未验证期间只能浏览已有内容。";
		copy.append(title, desc);
		const actions = document.createElement("div");
		actions.className = "verify-actions";
		const resend = document.createElement("button");
		resend.type = "button";
		resend.className = "verify-resend";
		resend.dataset.testid = "console-resend-verification";
		resend.textContent = "重新发送验证邮件";
		const status = document.createElement("div");
		status.className = "verify-status";
		status.dataset.testid = "console-verify-status";
		const startCooldown = (deadline: number, prefix: string): void => {
			const tick = (): void => {
				const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
				if (left <= 0) {
					if (resendTimer) clearInterval(resendTimer);
					resend.disabled = false;
					status.textContent = "现在可以重新发送了。";
					return;
				}
				status.textContent = `${prefix}${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} 后可重发。`;
			};
			tick();
			if (resendTimer) clearInterval(resendTimer);
			resendTimer = setInterval(tick, 1000);
		};
		resend.addEventListener("click", () => {
			void (async () => {
				resend.disabled = true;
				status.textContent = "正在发送…";
				try {
					const result = await client.resendVerification({
						email: account.primaryEmail,
					});
					const deadline = result.nextAllowedAt
						? new Date(result.nextAllowedAt).getTime()
						: Date.now() + 60_000;
					startCooldown(deadline, "验证邮件已发送，");
				} catch (error) {
					if (
						error instanceof DomApiError &&
						error.errorCode === "RATE_LIMITED"
					) {
						// 注册时已自动发送一封；429 不带服务端时间，按契约冷却窗兜底。
						status.textContent = "验证邮件刚发送过，请查收邮箱…";
						startCooldown(Date.now() + 60_000, "已发送，");
						return;
					}
					resend.disabled = false;
					status.textContent =
						error instanceof Error ? error.message : String(error);
				}
			})();
		});
		const goVerify = document.createElement("button");
		goVerify.type = "button";
		goVerify.className = "verify-link";
		goVerify.textContent = "前往验证页";
		goVerify.addEventListener("click", () => navigate("/verify-email"));
		actions.append(resend, goVerify);
		banner.append(iconWrap, copy, actions, status);
		main.append(banner);
	}

	const headerRow = document.createElement("div");
	headerRow.className = "content-header-row";
	const breadcrumb = document.createElement("div");
	breadcrumb.className = "breadcrumb-trail";
	const crumbWs = document.createElement("span");
	crumbWs.className = "breadcrumb-item";
	crumbWs.id = "mainBreadcrumbWorkspace";
	crumbWs.textContent = "…";
	crumbWs.addEventListener("click", () => {
		if (currentWorkspaceId) void loadProjects(currentWorkspaceId);
	});
	const crumbSep = document.createElement("span");
	crumbSep.className = "breadcrumb-sep";
	crumbSep.textContent = "/";
	const crumbProject = document.createElement("span");
	crumbProject.className = "breadcrumb-item current";
	crumbProject.id = "mainBreadcrumbProject";
	crumbProject.textContent = "…";
	breadcrumb.append(crumbWs, crumbSep, crumbProject);

	const headerActions = document.createElement("div");
	headerActions.className = "header-actions";
	const createStatus = document.createElement("span");
	createStatus.dataset.testid = "console-create-status";
	createStatus.style.fontSize = "12px";
	createStatus.style.color = "var(--ink-secondary)";
	const createBtn = document.createElement("button");
	createBtn.type = "button";
	createBtn.className = "btn-create-context";
	createBtn.dataset.testid = "console-create-resource";
	createBtn.append(svgIcon("plus", 14));
	const createLabel = document.createElement("span");
	createLabel.textContent = "新建文档";
	createBtn.append(createLabel);
	createBtn.addEventListener("click", () => {
		void (async () => {
			createStatus.textContent = "";
			if (!currentProject) {
				createStatus.textContent = "请先选择一个项目";
				return;
			}
			try {
				const created = await client.createResource({
					projectId: currentProject.projectId,
					resourceType: "document",
					name: "无标题文稿",
					idempotencyKey: crypto.randomUUID(),
				});
				navigate(`/editor?resource=${created.resourceId}`);
			} catch (error) {
				createStatus.textContent =
					error instanceof Error ? error.message : String(error);
			}
		})();
	});
	headerActions.append(createStatus, createBtn);
	headerRow.append(breadcrumb, headerActions);

	// 资源表格
	const listArea = document.createElement("div");
	listArea.className = "resource-list-container";
	listArea.id = "resourceListArea";
	const table = document.createElement("table");
	table.className = "resource-table";
	const thead = document.createElement("thead");
	const headRow = document.createElement("tr");
	for (const [label, width] of [
		["资源名称", "50%"],
		["类型", "25%"],
		["生命周期", "25%"],
	] as const) {
		const th = document.createElement("th");
		th.textContent = label;
		if (width) th.style.width = width;
		headRow.append(th);
	}
	thead.append(headRow);
	const tbody = document.createElement("tbody");
	tbody.id = "resourceTableBody";
	table.append(thead, tbody);
	listArea.append(table);

	const emptyHost = document.createElement("div");
	emptyHost.id = "emptyStatePlaceholder";
	emptyHost.dataset.testid = "console-empty-state";

	main.append(headerRow, listArea, emptyHost);
	body.append(sidebar, main, sidebarBackdrop);
	shell.append(topbar, body);

	/* ---------------- Cmd+K 命令面板 ---------------- */
	const palette = document.createElement("div");
	palette.className = "cmd-palette-backdrop";
	palette.id = "cmdPaletteBackdrop";
	palette.dataset.testid = "search-panel";
	palette.addEventListener("click", (event) => {
		if (event.target === palette) closePalette();
	});
	const paletteModal = document.createElement("div");
	paletteModal.className = "cmd-palette-modal";
	const inputBox = document.createElement("div");
	inputBox.className = "palette-input-box";
	inputBox.append(svgIcon("search", 18));
	const paletteInput = document.createElement("input");
	paletteInput.type = "text";
	paletteInput.className = "palette-input";
	paletteInput.id = "paletteInput";
	paletteInput.dataset.testid = "search-input";
	paletteInput.placeholder = "输入资源名称或路径快速跳转…";
	paletteInput.setAttribute("aria-label", "搜索资源");
	const escHint = document.createElement("span");
	escHint.className = "search-shortcut-pill";
	escHint.textContent = "ESC 关闭";
	inputBox.append(paletteInput, escHint);
	const results = document.createElement("ul");
	results.className = "palette-results-list";
	results.dataset.testid = "search-results";
	const historyList = document.createElement("ul");
	historyList.className = "palette-results-list";
	historyList.dataset.testid = "search-history";
	const searchRun = document.createElement("button");
	searchRun.type = "button";
	searchRun.dataset.testid = "search-run";
	searchRun.textContent = "搜索";
	searchRun.addEventListener("click", () => void runSearch(paletteInput.value));
	const clearHistory = document.createElement("button");
	clearHistory.type = "button";
	clearHistory.dataset.testid = "search-history-clear";
	clearHistory.textContent = "清空历史";
	clearHistory.addEventListener("click", () => {
		void (async () => {
			try {
				await client.clearSearchHistory();
				historyList.replaceChildren();
			} catch {
				// best-effort; API envelope surfaces on failure
			}
		})();
	});
	const paletteFooter = document.createElement("div");
	paletteFooter.style.display = "flex";
	paletteFooter.style.gap = "8px";
	paletteFooter.style.padding = "8px 12px";
	paletteFooter.style.borderTop = "1px solid rgba(244, 165, 115, 0.16)";
	paletteFooter.append(searchRun, clearHistory);
	paletteModal.append(inputBox, results, historyList, paletteFooter);
	palette.append(paletteModal);
	app.append(shell, palette);

	/* ---------------- 通知渲染 ---------------- */
	const renderNotifications = async (): Promise<void> => {
		try {
			const result = await client.listNotifications();
			bellDot.classList.toggle(
				"show",
				(result.unreadCount ?? 0) > 0 || result.items.length > 0,
			);
			if (result.unreadCount != null && result.unreadCount > 0) {
				bellDot.textContent = String(result.unreadCount);
				bellDot.style.width = "auto";
				bellDot.style.minWidth = "8px";
				bellDot.style.padding = "0 3px";
			}
			notifDropdown.replaceChildren();
			const title = document.createElement("div");
			title.style.cssText =
				"padding:6px 10px;font-family:var(--font-display);font-size:13px;font-weight:700;color:var(--ink-primary);border-bottom:1px solid rgba(244,165,115,0.15);margin-bottom:4px;";
			title.textContent = `未读动态 (${result.unreadCount ?? 0})`;
			notifDropdown.append(title);
			if (result.items.length === 0) {
				const empty = document.createElement("div");
				empty.className = "dropdown-item";
				empty.textContent = "暂无通知";
				notifDropdown.append(empty);
				return;
			}
			for (const notification of result.items as NotificationItem[]) {
				const row = document.createElement("div");
				row.className = "dropdown-item";
				row.style.cssText =
					"flex-direction:column;align-items:flex-start;gap:2px;";
				row.dataset.testid = "notification-row";
				const line = document.createElement("div");
				line.style.fontSize = "12.5px";
				line.style.fontWeight = "600";
				line.textContent = `${notification.kind}${
					notification.payload?.excerpt
						? `：${notification.payload.excerpt}`
						: ""
				}`;
				row.append(line);
				row.addEventListener("click", (event) => {
					event.stopPropagation();
					void (async () => {
						try {
							await client.markNotificationRead(notification.notificationId);
						} catch {
							// best-effort read-marking; the jump still happens
						}
						if (notification.payload?.resourceId) {
							navigate(`/editor?resource=${notification.payload.resourceId}`);
						}
					})();
				});
				notifDropdown.append(row);
			}
			const readAll = document.createElement("div");
			readAll.className = "dropdown-item";
			readAll.dataset.testid = "notifications-read-all";
			readAll.textContent = "全部已读";
			readAll.addEventListener("click", (event) => {
				event.stopPropagation();
				void (async () => {
					try {
						await client.markAllNotificationsRead();
						await renderNotifications();
					} catch {
						// best-effort UI
					}
				})();
			});
			notifDropdown.append(readAll);
		} catch {
			notifDropdown.replaceChildren();
		}
	};
	void renderNotifications();

	/* ---------------- 树渲染 ---------------- */
	const renderWorkspaceRows = (): void => {
		list.replaceChildren();
		if (workspaces.length === 0) {
			const empty = document.createElement("li");
			empty.dataset.testid = "workspace-empty";
			empty.className = "tree-node-row";
			empty.textContent = "暂无工作区";
			list.append(empty);
			return;
		}
		for (const ws of workspaces) {
			const li = document.createElement("li");
			const row = document.createElement("button");
			row.type = "button";
			row.className = "tree-node-row";
			row.dataset.testid = "workspace-row";
			const arrow = document.createElement("span");
			arrow.className = "tree-node-arrow";
			arrow.append(svgIcon("chevron", 10));
			row.append(arrow);
			row.append(svgIcon("workspace", 15));
			const label = document.createElement("span");
			label.textContent = `${ws.name} (${ws.membershipKind})`;
			row.append(label);
			const projects = document.createElement("ul");
			projects.dataset.testid = "project-list";
			projects.className = "tree-nested-group";
			projects.style.display = "none";
			row.addEventListener("click", () => {
				// 幂等展开：点击恒为“加载并展开”，不折叠（E2E/旧语义：点击工作区行即露出项目）。
				arrow.classList.add("expanded");
				projects.style.display = "flex";
				if (projects.dataset.loaded !== "true") {
					projects.dataset.loaded = "true";
					void loadProjects(ws.workspaceId, projects);
				}
			});
			li.append(row, projects);
			list.append(li);
			// 默认展开第一个工作区并加载其项目
			if (ws.workspaceId === currentWorkspaceId) {
				arrow.classList.add("expanded");
				projects.style.display = "flex";
				void loadProjects(ws.workspaceId, projects);
			}
		}
	};

	const renderProjectRows = (
		projectsUl: HTMLUListElement,
		items: ProjectRef[],
	): void => {
		projectsUl.replaceChildren();
		for (const project of items) {
			const li = document.createElement("li");
			const row = document.createElement("button");
			row.type = "button";
			row.className = "tree-node-row";
			row.dataset.testid = "project-row";
			row.append(svgIcon("folder", 15));
			const label = document.createElement("span");
			label.textContent = project.name;
			row.append(label);
			const resources = document.createElement("ul");
			resources.dataset.testid = "resource-list";
			resources.className = "tree-nested-group";
			resources.style.display = "none";
			row.addEventListener("click", (event) => {
				event.stopPropagation();
				selectProject(project);
				const hidden = resources.style.display === "none";
				resources.style.display = hidden ? "flex" : "none";
				if (hidden) void loadResources(project, resources);
			});
			li.append(row, resources);
			projectsUl.append(li);
		}
	};

	const renderResourceRows = (
		resourcesUl: HTMLUListElement | null,
		items: ResourceRef[],
		target: "tree" | "table",
	): void => {
		if (target === "table") {
			tbody.replaceChildren();
			for (const res of items) {
				tbody.append(buildResourceRow(res, "console-resource-row"));
			}
			return;
		}
		if (!resourcesUl) return;
		resourcesUl.replaceChildren();
		for (const res of items) {
			const li = document.createElement("li");
			const row = document.createElement("button");
			row.type = "button";
			row.className = "tree-node-row";
			row.dataset.testid = "resource-row";
			row.style.width = "100%";
			const { icon } = resourceTypeIcon(res.resourceType, 13);
			row.append(svgIcon("chevron", 8));
			row.append(icon);
			const label = document.createElement("span");
			label.textContent = res.name;
			row.append(label);
			row.addEventListener("click", (event) => {
				event.stopPropagation();
				navigate(`/editor?resource=${res.resourceId}`);
			});
			li.append(row);
			resourcesUl.append(li);
		}
	};

	const buildResourceRow = (
		res: ResourceRef,
		testid: string,
	): HTMLTableRowElement => {
		const tr = document.createElement("tr");
		tr.className = "resource-row";
		tr.dataset.testid = testid;
		const tdTitle = document.createElement("td");
		const titleCell = document.createElement("div");
		titleCell.className = "resource-title-cell";
		const { icon, className } = resourceTypeIcon(res.resourceType, 22);
		const iconWrap = document.createElement("div");
		iconWrap.className = `resource-type-icon ${className}`;
		iconWrap.append(icon);
		const nameSpan = document.createElement("span");
		nameSpan.className = "resource-title-text";
		nameSpan.textContent = res.name;
		nameSpan.title = res.name;
		titleCell.append(iconWrap, nameSpan);
		tdTitle.append(titleCell);
		const metaSlot = document.createElement("div");
		metaSlot.className = "mobile-meta-slot";
		const typeMeta = document.createElement("span");
		typeMeta.textContent = RESOURCE_TYPE_LABEL[res.resourceType];
		const lifeMeta = document.createElement("span");
		lifeMeta.className =
			res.lifecycle === "Active"
				? "lifecycle-badge"
				: "lifecycle-badge trashed";
		lifeMeta.textContent = res.lifecycle;
		metaSlot.append(typeMeta, lifeMeta);
		tdTitle.append(metaSlot);
		tr.append(tdTitle);
		const tdType = document.createElement("td");
		tdType.textContent = RESOURCE_TYPE_LABEL[res.resourceType];
		tdType.style.color = "var(--ink-secondary)";
		const tdLife = document.createElement("td");
		const lifeBadge = document.createElement("span");
		lifeBadge.className =
			res.lifecycle === "Active"
				? "lifecycle-badge"
				: "lifecycle-badge trashed";
		lifeBadge.textContent = res.lifecycle;
		tdLife.append(lifeBadge);
		tr.append(tdType, tdLife);
		tr.addEventListener("click", () => {
			if (res.lifecycle === "Active") {
				navigate(`/editor?resource=${res.resourceId}`);
			}
		});
		return tr;
	};

	/* ---------------- 数据加载 ---------------- */
	const loadProjects = async (
		workspaceId: string,
		projectsUl?: HTMLUListElement,
	): Promise<void> => {
		try {
			const result = await client.listProjects(workspaceId);
			const items: ProjectRef[] = result.items.map((item) => ({
				projectId: item.projectId,
				name: item.name,
			}));
			currentWorkspaceId = workspaceId;
			if (items.length === 0) {
				renderEmptyState("no-projects");
				return;
			}
			if (projectsUl) renderProjectRows(projectsUl, items);
			selectProject(items[0]);
		} catch {
			if (projectsUl) projectsUl.replaceChildren();
		}
	};

	const loadResources = async (
		project: ProjectRef,
		resourcesUl?: HTMLUListElement,
	): Promise<void> => {
		try {
			const result = await client.listResources(project.projectId);
			const items: ResourceRef[] = result.items.filter(
				(res): res is ResourceRef =>
					res.lifecycle === "Active" || res.lifecycle === "Trashed",
			);
			currentProject = project;
			crumbProject.textContent = project.name;
			trashRow.classList.remove("active");
			if (items.length === 0) {
				renderEmptyState("no-resources");
				return;
			}
			renderResourceRows(resourcesUl ?? null, items, "table");
			if (resourcesUl) renderResourceRows(resourcesUl, items, "tree");
		} catch {
			renderEmptyState("no-resources");
		}
	};

	const openTrashView = async (): Promise<void> => {
		document
			.querySelectorAll<HTMLElement>(".console-sidebar .tree-node-row")
			.forEach((row) => {
				row.classList.remove("active");
			});
		trashRow.classList.add("active");
		crumbProject.textContent = "回收站";
		createBtn.style.display = "none";
		try {
			if (!currentWorkspaceId) return;
			const projects = await client.listProjects(currentWorkspaceId);
			const trashed: ResourceRef[] = [];
			for (const project of projects.items) {
				const resources = await client.listResources(project.projectId);
				for (const res of resources.items) {
					if (res.lifecycle !== "Active") {
						trashed.push({
							resourceId: res.resourceId,
							name: res.name,
							resourceType: res.resourceType as ResourceType,
							lifecycle: res.lifecycle,
						});
					}
				}
			}
			if (trashed.length === 0) {
				renderEmptyState("trash-empty");
				return;
			}
			renderResourceRows(
				null,
				trashed.map((res) => ({ ...res, lifecycle: "Trashed" })),
				"table",
			);
		} catch {
			renderEmptyState("trash-empty");
		}
	};

	/* ---------------- 空态 ---------------- */
	const renderEmptyState = (
		kind: "no-workspace" | "no-projects" | "no-resources" | "trash-empty",
	): void => {
		listArea.style.display = "none";
		if (pendingVerification) createBtn.style.display = "none";
		emptyHost.style.display = "flex";
		emptyHost.replaceChildren();
		let card: HTMLElement;
		if (kind === "no-workspace" && pendingVerification) {
			// 未验证账户创建必 403：空态直接给验证引导而非创建按钮。
			const goVerify = document.createElement("button");
			goVerify.type = "button";
			goVerify.className = "btn-create-context";
			goVerify.dataset.testid = "console-empty-verify";
			goVerify.textContent = "前往验证邮箱";
			goVerify.addEventListener("click", () => navigate("/verify-email"));
			card = emptyStateCard({
				title: "先完成邮箱验证",
				description:
					"验证通过后，这里会出现你的第一座数字墨屿。验证邮件已发送至你的邮箱，也可以点下方按钮重新发送。",
				illustration: illustrationNoWorkspace(),
				actions: [goVerify],
			});
		} else if (kind === "no-workspace") {
			const create = document.createElement("button");
			create.type = "button";
			create.className = "btn-create-context";
			create.textContent = "创建第一个工作区";
			create.addEventListener("click", () => {
				void (async () => {
					try {
						await client.createWorkspace({
							name: "我的工作区",
							idempotencyKey: crypto.randomUUID(),
						});
						await boot();
					} catch (error) {
						create.textContent =
							error instanceof Error ? error.message : String(error);
					}
				})();
			});
			card = emptyStateCard({
				title: "还没有属于你的工作区",
				description:
					"慢下来，在这里搭建属于你的第一座数字墨屿。工作区是团队协同、沉淀知识与组织资产的出发点。",
				illustration: illustrationNoWorkspace(),
				actions: [create],
			});
		} else if (kind === "no-projects") {
			card = emptyStateCard({
				title: "当前工作区暂无项目",
				description:
					"项目是整理多篇文档与协同工程的容器。建立一个新项目，让灵感与思考井然有序。",
				illustration: illustrationNoProjects(),
				actions: [],
			});
		} else if (kind === "trash-empty") {
			card = emptyStateCard({
				title: "回收站是空的",
				description: "删除的资源会安静地躺在这里，等待被找回或永远告别。",
				illustration: illustrationNoResources(),
				actions: [],
			});
		} else {
			const createRes = document.createElement("button");
			createRes.type = "button";
			createRes.className = "btn-create-context";
			createRes.textContent = "新建文档";
			createRes.addEventListener("click", () => {
				if (!currentProject) return;
				void (async () => {
					try {
						const created = await client.createResource({
							projectId: currentProject.projectId,
							resourceType: "document",
							name: "新文档",
							idempotencyKey: crypto.randomUUID(),
						});
						navigate(`/editor?resource=${created.resourceId}`);
					} catch (error) {
						createRes.textContent =
							error instanceof Error ? error.message : String(error);
					}
				})();
			});
			card = emptyStateCard({
				title: "这个项目还是空的",
				description:
					"落笔成文，代码成篇。开始你的第一篇创作吧，每一次保存都会记录在幂等日志中。",
				illustration: illustrationNoResources(),
				actions: [createRes],
			});
		}
		emptyHost.append(card);
	};

	const showNormalList = (): void => {
		listArea.style.display = "block";
		emptyHost.style.display = "none";
		createBtn.style.display = "";
	};

	/* ---------------- Cmd+K 搜索 ---------------- */
	let paletteItems: Array<{ resourceId: string; name: string }> = [];
	let paletteIndex = 0;
	const openPalette = (): void => {
		palette.classList.add("show");
		paletteInput.value = "";
		paletteIndex = 0;
		renderSearchHistory();
		paletteInput.focus();
	};
	const closePalette = (): void => palette.classList.remove("show");

	const renderSearchHistory = (): void => {
		historyList.replaceChildren();
		void (async () => {
			try {
				const history = await client.searchHistory();
				for (const entry of history.items) {
					const li = document.createElement("li");
					li.className = "palette-result-item";
					li.textContent = entry.query;
					li.style.fontSize = "13px";
					li.addEventListener("click", () => {
						paletteInput.value = entry.query;
						void runSearch(entry.query);
					});
					historyList.append(li);
				}
			} catch {
				// history is best-effort
			}
		})();
	};

	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	paletteInput.addEventListener("input", () => {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => void runSearch(paletteInput.value), 250);
	});

	const runSearch = async (query: string): Promise<void> => {
		if (!currentWorkspaceId) {
			renderEmptyResult("请先在左侧选择工作区");
			return;
		}
		results.replaceChildren();
		if (query.trim().length === 0) {
			paletteItems = [];
			return;
		}
		try {
			const result = await client.searchWorkspace(currentWorkspaceId, query);
			paletteItems = result.items.map((item) => ({
				resourceId: item.resourceId,
				name: item.name,
			}));
			paletteIndex = 0;
			results.replaceChildren();
			if (result.items.length === 0) {
				renderEmptyResult("无结果");
				return;
			}
			result.items.forEach((item, index) => {
				const li = document.createElement("li");
				li.className = "palette-result-item";
				li.dataset.testid = "search-result-row";
				if (index === 0) li.classList.add("active");
				li.dataset.index = String(index);
				const left = document.createElement("div");
				left.className = "palette-result-left";
				const { icon, className } = resourceTypeIcon(
					item.resourceType as ResourceType,
					14,
				);
				const iconWrap = document.createElement("div");
				iconWrap.className = `resource-type-icon ${className}`;
				iconWrap.style.width = "22px";
				iconWrap.style.height = "22px";
				iconWrap.append(icon);
				const name = document.createElement("span");
				name.textContent = item.name;
				left.append(iconWrap, name);
				li.append(left);
				li.addEventListener("click", () => {
					navigate(`/editor?resource=${item.resourceId}`);
				});
				results.append(li);
			});
		} catch (error) {
			renderEmptyResult(error instanceof Error ? error.message : "搜索失败");
		}
	};

	const renderEmptyResult = (text: string): void => {
		paletteItems = [];
		results.replaceChildren();
		const li = document.createElement("li");
		li.dataset.testid = "search-empty";
		li.textContent = text;
		li.style.padding = "10px 14px";
		li.style.color = "var(--ink-muted)";
		li.style.fontSize = "13px";
		results.append(li);
	};

	const movePalette = (direction: 1 | -1): void => {
		if (paletteItems.length === 0) return;
		paletteIndex =
			(paletteIndex + direction + paletteItems.length) % paletteItems.length;
		results
			.querySelectorAll("[data-testid=search-result-row]")
			.forEach((li) => {
				li.classList.toggle(
					"active",
					Number((li as HTMLElement).dataset.index) === paletteIndex,
				);
			});
	};

	paletteInput.addEventListener("keydown", (event) => {
		if (event.key === "ArrowDown") {
			event.preventDefault();
			movePalette(1);
		} else if (event.key === "ArrowUp") {
			event.preventDefault();
			movePalette(-1);
		} else if (event.key === "Enter") {
			event.preventDefault();
			const target = paletteItems[paletteIndex];
			if (target) navigate(`/editor?resource=${target.resourceId}`);
		}
	});

	window.addEventListener("keydown", (event) => {
		if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
			event.preventDefault();
			openPalette();
		}
		if (event.key === "Escape") {
			closePalette();
			closeMobileSidebar();
		}
	});

	/* ---------------- 下拉切换 ---------------- */
	const toggleDropdown = (
		id: "wsDropdown" | "notifDropdown" | "accountDropdown",
	) => {
		const map = {
			wsDropdown,
			notifDropdown,
			accountDropdown,
		} as const;
		const dropdowns = [wsDropdown, notifDropdown, accountDropdown];
		const target = map[id];
		const wasOpen = target.classList.contains("show");
		dropdowns.forEach((d) => {
			d.classList.remove("show");
		});
		if (!wasOpen) target.classList.add("show");
	};

	window.addEventListener("click", (event) => {
		const target = event.target as HTMLElement;
		if (
			!target.closest(".ws-switcher-btn") &&
			!target.closest("#wsDropdown") &&
			!target.closest(".icon-btn-quiet") &&
			!target.closest(".account-menu-trigger")
		) {
			[wsDropdown, notifDropdown, accountDropdown].forEach((d) => {
				d.classList.remove("show");
			});
		}
	});

	/* ---------------- 手机侧栏 ---------------- */
	const toggleMobileSidebar = (): void => {
		const open = sidebar.classList.contains("mobile-open");
		sidebar.classList.toggle("mobile-open", !open);
		sidebarBackdrop.classList.toggle("show", !open);
	};
	const closeMobileSidebar = (): void => {
		sidebar.classList.remove("mobile-open");
		sidebarBackdrop.classList.remove("show");
	};

	/* ---------------- 账号菜单 ---------------- */
	accountDropdown.replaceChildren();
	const accountTitle = document.createElement("div");
	accountTitle.style.cssText =
		"padding:8px 12px;font-size:12px;color:var(--ink-muted);border-bottom:1px solid rgba(244,165,115,0.15);";
	accountTitle.textContent = `当前账号: ${account.primaryEmail}`;
	const logoutItem = document.createElement("div");
	logoutItem.className = "dropdown-item danger";
	logoutItem.dataset.testid = "logout-button";
	logoutItem.append(svgIcon("logout", 14));
	const logoutLabel = document.createElement("span");
	logoutLabel.textContent = "退出登录";
	logoutItem.append(logoutLabel);
	logoutItem.addEventListener("click", () => {
		void (async () => {
			try {
				await client.logout();
			} finally {
				navigate("/login");
			}
		})();
	});
	accountDropdown.append(accountTitle, logoutItem);

	/* ---------------- 初始化 ---------------- */
	async function selectProject(project: ProjectRef): Promise<void> {
		document
			.querySelectorAll<HTMLElement>(".console-sidebar .tree-node-row")
			.forEach((row) => {
				row.classList.remove("active");
			});
		trashRow.classList.remove("active");
		currentProject = project;
		currentWorkspaceName = wsName.textContent ?? currentWorkspaceName;
		crumbProject.textContent = project.name;
		showNormalList();
		void loadResources(project);
	}

	const boot = async (): Promise<void> => {
		try {
			const result = await client.listWorkspaces();
			workspaces = result.workspaces.map((ws) => ({
				workspaceId: ws.workspaceId,
				name: ws.name,
				membershipKind: ws.membershipKind,
			}));
			if (workspaces.length === 0) {
				wsName.textContent = "无工作区";
				wsRole.textContent = "";
				renderWorkspaceRows();
				renderEmptyState("no-workspace");
				return;
			}
			const first = workspaces[0];
			currentWorkspaceId = first.workspaceId;
			currentWorkspaceName = first.name;
			renderWorkspaceRows();
			wsName.textContent = first.name;
			wsRole.textContent = first.membershipKind;
			wsDropdown.replaceChildren();
			workspaces.forEach((ws) => {
				const item = document.createElement("div");
				item.className = "dropdown-item";
				if (ws.workspaceId === currentWorkspaceId) {
					item.classList.add("active");
				}
				item.append(svgIcon("workspace", 14));
				const itemLabel = document.createElement("span");
				itemLabel.textContent = ws.name;
				item.append(itemLabel);
				const pill = document.createElement("span");
				pill.className = "ws-role-pill";
				pill.style.marginLeft = "auto";
				pill.textContent = ws.membershipKind;
				item.append(pill);
				item.addEventListener("click", () => {
					currentWorkspaceId = ws.workspaceId;
					currentWorkspaceName = ws.name;
					wsName.textContent = ws.name;
					wsRole.textContent = ws.membershipKind;
					wsDropdown.classList.remove("show");
					void bootProjectList(ws.workspaceId);
				});
				wsDropdown.append(item);
			});
			await bootProjectList(first.workspaceId);
		} catch {
			wsName.textContent = "加载失败";
		}
	};

	async function bootProjectList(workspaceId: string): Promise<void> {
		showNormalList();
		try {
			const result = await client.listProjects(workspaceId);
			const items: ProjectRef[] = result.items.map((item) => ({
				projectId: item.projectId,
				name: item.name,
			}));
			crumbWs.textContent = currentWorkspaceName;
			if (items.length === 0) {
				currentProject = null;
				crumbProject.textContent = "暂无项目";
				renderEmptyState("no-projects");
				return;
			}
			currentProject = items[0];
			crumbProject.textContent = items[0].name;
			void loadResources(items[0]);
		} catch {
			renderEmptyState("no-projects");
		}
	}

	void boot();
}
