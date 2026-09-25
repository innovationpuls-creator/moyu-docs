import { createTextDocument } from "@dom/editor-core";
import {
	useMutation,
	useQueries,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { client } from "../../shared/api/client";
import { resourceRuntime } from "../../shared/api/resource-runtime";
import { useShellUiStore } from "../../shared/ui-store";
import { NotificationCenter } from "../notifications";
import { SearchPalette } from "../search";
import { WorkspaceMembersPanel } from "./members-panel";

export { InvitationAcceptPage } from "./invitation-accept-page";

type Workspace = Awaited<
	ReturnType<typeof client.listWorkspaces>
>["workspaces"][number];
type Project = Awaited<ReturnType<typeof client.listProjects>>["items"][number];
type Resources = Awaited<ReturnType<typeof client.listResources>>["items"];
type Resource = Resources[number];
type ResourceType = Resource["resourceType"];
type Folder = Awaited<
	ReturnType<typeof client.getProjectTree>
>["folders"][number];
type CreateKind = "workspace" | "project" | "folder" | ResourceType;
type UnsyncedDraft = Awaited<
	ReturnType<typeof resourceRuntime.listUnsyncedResources>
>[number];

function downloadUnsyncedDrafts(drafts: UnsyncedDraft[]): void {
	const content = drafts
		.map((draft) => {
			const [first, ...rest] = draft.snapshots;
			const document = createTextDocument(first?.update);
			for (const snapshot of rest) document.applyRemoteUpdate(snapshot.update);
			document.flushLocalUpdates();
			const title = draft.resource.name.replace(/[\r\n]+/g, " ").trim();
			const body = document.getText();
			document.destroy();
			return `# ${title || "未命名文档"}\n\n${body}`;
		})
		.join("\n\n---\n\n");
	const url = URL.createObjectURL(
		new Blob([content], { type: "text/markdown;charset=utf-8" }),
	);
	const link = window.document.createElement("a");
	link.href = url;
	link.download = `dom-offline-drafts-${new Date().toISOString().slice(0, 10)}.md`;
	link.click();
	window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Icon({ name }: { name: string }) {
	const d: Record<string, string> = {
		workspace: "M3 5h18v14H3z M8 9h8 M8 13h5",
		search: "m20 20-4.3-4.3 M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z",
		bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4",
		folder: "M3 6h7l2 2h9v10H3z",
		document: "M6 3h8l4 4v14H6z M14 3v5h5 M9 12h6 M9 16h6",
		code: "m8 8-4 4 4 4 M16 8l4 4-4 4 M14 5l-4 14",
		markdown: "M4 5h16v14H4z M7 15V9l3 3 3-3v6 M16 10v5m-2-2 2 2 2-2",
		text: "M5 5h14 M12 5v14 M8 19h8",
		trash: "M4 7h16 M9 7V4h6v3m3 0-1 14H7L6 7",
		chevron: "m9 18 6-6-6-6",
		plus: "M12 5v14 M5 12h14",
		user: "M20 21a8 8 0 0 0-16 0 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
		menu: "M4 6h16 M4 12h16 M4 18h16",
	};
	return (
		<svg
			width="16"
			height="16"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.8"
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
		>
			<path d={d[name] ?? d.document} />
		</svg>
	);
}

function ResourceIcon({ type }: { type: ResourceType }) {
	return (
		<span className={"resource-type-icon type-" + type}>
			<Icon name={type} />
		</span>
	);
}

function EmptyState({
	title,
	description,
	action,
	onAction,
	extra,
}: {
	title: string;
	description: string;
	action?: string;
	onAction?: () => void;
	extra?: React.ReactNode;
}) {
	return (
		<section className="console-empty-state" data-testid="console-empty-state">
			<div className="empty-orbit" aria-hidden="true">
				<span />
				<i />
				<b />
			</div>
			<h1>{title}</h1>
			<p>{description}</p>
			<div className="empty-actions">
				{action && (
					<button
						type="button"
						className="btn-create-context"
						onClick={onAction}
					>
						{action}
					</button>
				)}
				{extra}
			</div>
		</section>
	);
}

function CreateDialog({
	kind,
	workspaceId,
	projectId,
	folderId,
	onClose,
}: {
	kind: CreateKind;
	workspaceId: string | null;
	projectId: string | null;
	folderId: string | null;
	onClose(): void;
}) {
	const cache = useQueryClient();
	const [name, setName] = useState("");
	const [error, setError] = useState("");
	const [resourceType, setResourceType] = useState<ResourceType>("document");
	const navigate = useNavigate();
	const chosenResourceType = kind === "document" ? resourceType : kind;
	const mutation = useMutation({
		mutationFn: async () => {
			if (kind === "workspace")
				return client.createWorkspace({
					name: name.trim(),
					idempotencyKey: crypto.randomUUID(),
				});
			if (kind === "project" && workspaceId)
				return client.createProject(workspaceId, {
					name: name.trim(),
					idempotencyKey: crypto.randomUUID(),
				});
			if (kind === "folder" && projectId)
				return client.createFolder(projectId, {
					parentFolderId: folderId,
					name: name.trim(),
					idempotencyKey: crypto.randomUUID(),
				});
			if (
				projectId &&
				["document", "code", "markdown", "text"].includes(chosenResourceType)
			) {
				return client.createResource({
					projectId,
					folderId: folderId ?? undefined,
					resourceType: chosenResourceType as ResourceType,
					name: name.trim(),
					idempotencyKey: crypto.randomUUID(),
				});
			}
			throw new Error("请先选择工作区或项目");
		},
		onSuccess: async (result) => {
			await cache.invalidateQueries();
			if ("resourceId" in result) {
				navigate("/editor?resourceId=" + encodeURIComponent(result.resourceId));
				return;
			}
			onClose();
		},
		onError: (reason) =>
			setError(reason instanceof Error ? reason.message : String(reason)),
	});
	const title =
		kind === "document" && resourceType !== "document"
			? `新建${resourceType === "markdown" ? " Markdown" : resourceType === "code" ? "代码文件" : "文本"}`
			: kind === "workspace"
				? "新建工作区"
				: kind === "project"
					? "新建项目"
					: kind === "folder"
						? "新建文件夹"
						: "新建" +
							(kind === "markdown"
								? " Markdown"
								: kind === "code"
									? "代码文件"
									: kind === "text"
										? "文本"
										: "文档");
	return (
		<div
			className="console-modal-backdrop"
			role="dialog"
			aria-modal="true"
			aria-label={title}
		>
			<form
				className="console-modal"
				onSubmit={(event) => {
					event.preventDefault();
					setError("");
					mutation.mutate();
				}}
			>
				<h2>{title}</h2>
				<label htmlFor="create-name">名称</label>
				<input
					id="create-name"
					required
					maxLength={200}
					value={name}
					onChange={(event) => setName(event.target.value)}
				/>
				{kind === "document" && (
					<label className="resource-type-picker">
						资源类型
						<select
							value={resourceType}
							onChange={(event) =>
								setResourceType(event.target.value as ResourceType)
							}
						>
							<option value="document">文档</option>
							<option value="markdown">Markdown</option>
							<option value="code">代码</option>
							<option value="text">文本</option>
						</select>
					</label>
				)}
				{error && (
					<p className="console-error" role="alert">
						{error}
					</p>
				)}
				<div className="console-modal-actions">
					<button type="button" className="btn-quiet" onClick={onClose}>
						取消
					</button>
					<button
						type="submit"
						className="btn-create-context"
						disabled={mutation.isPending}
					>
						{mutation.isPending ? "创建中…" : "创建"}
					</button>
				</div>
			</form>
		</div>
	);
}

function FolderTree({
	projectId,
	folders,
	resources,
	selectedFolderId,
	onSelect,
	onOpen,
	onCreate,
}: {
	projectId: string;
	folders: Folder[];
	resources: Resource[];
	selectedFolderId: string | null;
	onSelect(id: string): void;
	onOpen(id: string): void;
	onCreate(kind: CreateKind, folderId: string | null): void;
}) {
	const [expanded, setExpanded] = useState<Set<string>>(
		() =>
			new Set(
				folders
					.filter((folder) => folder.hasChildren)
					.map((folder) => folder.folderId),
			),
	);
	function folderNode(folder: Folder, depth: number): React.ReactNode {
		const childFolders = folders.filter(
			(candidate) =>
				candidate.parentFolderId === folder.folderId &&
				candidate.lifecycle === "Active",
		);
		const childResources = resources.filter(
			(resource) =>
				resource.folderId === folder.folderId &&
				resource.lifecycle === "Active",
		);
		const open = expanded.has(folder.folderId);
		return (
			<div
				key={folder.folderId}
				className="console-tree-node"
				data-testid={"console-tree-folder-" + folder.folderId}
			>
				<div
					className={
						"tree-node-row " +
						(selectedFolderId === folder.folderId ? "active" : "")
					}
					style={{ paddingLeft: 6 + depth * 13 }}
				>
					<button
						type="button"
						className={"tree-disclosure " + (open ? "expanded" : "")}
						aria-label={(open ? "折叠 " : "展开 ") + folder.name}
						onClick={() =>
							setExpanded((old) => {
								const next = new Set(old);
								if (next.has(folder.folderId)) next.delete(folder.folderId);
								else next.add(folder.folderId);
								return next;
							})
						}
					>
						<Icon name="chevron" />
					</button>
					<button
						type="button"
						className="tree-select"
						onClick={() => onSelect(folder.folderId)}
					>
						<Icon name="folder" />
						<span>{folder.name}</span>
					</button>
					<button
						type="button"
						className="tree-add"
						aria-label={"在" + folder.name + "中新建"}
						onClick={() => onCreate("document", folder.folderId)}
					>
						<Icon name="plus" />
					</button>
				</div>
				{open && (
					<div className="tree-nested-group">
						{childFolders.map((child) => folderNode(child, depth + 1))}
						{childResources.map((resource) => (
							<button
								key={resource.resourceId}
								type="button"
								className="tree-resource-row"
								data-testid={`console-tree-resource-${resource.resourceId}`}
								style={{ paddingLeft: 22 + depth * 13 }}
								onClick={() => onOpen(resource.resourceId)}
							>
								<ResourceIcon type={resource.resourceType} />
								<span>{resource.name}</span>
							</button>
						))}
					</div>
				)}
			</div>
		);
	}
	return (
		<div className="console-folder-tree">
			{folders
				.filter(
					(folder) =>
						folder.parentFolderId === null && folder.lifecycle === "Active",
				)
				.map((folder) => folderNode(folder, 0))}
			<span className="sr-only">{projectId}</span>
		</div>
	);
}

export function WorkspacePage() {
	const navigate = useNavigate();
	const cache = useQueryClient();
	const [params, setParams] = useSearchParams();
	const [workspaceMenu, setWorkspaceMenu] = useState(false);
	const [accountMenu, setAccountMenu] = useState(false);
	const [membersPanelOpen, setMembersPanelOpen] = useState(false);
	const sidebarOpen = useShellUiStore((state) => state.sidebarOpen);
	const setSidebarOpen = useShellUiStore((state) => state.setSidebarOpen);
	const [create, setCreate] = useState<{
		kind: CreateKind;
		projectId: string | null;
		folderId: string | null;
	} | null>(null);
	const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);
	const [logoutDrafts, setLogoutDrafts] = useState<UnsyncedDraft[] | null>(
		null,
	);
	const [logoutError, setLogoutError] = useState("");
	const [logoutBusy, setLogoutBusy] = useState(false);
	const workspaceQuery = useQuery({
		queryKey: ["workspaces"],
		queryFn: () => client.listWorkspaces(),
	});
	const accountQuery = useQuery({
		queryKey: ["account"],
		queryFn: () => client.me(),
	});
	const workspaces = workspaceQuery.data?.workspaces ?? [];
	const workspaceId =
		params.get("workspaceId") ?? workspaces[0]?.workspaceId ?? null;
	const workspace =
		workspaces.find((item) => item.workspaceId === workspaceId) ?? null;
	const projectsQuery = useQuery({
		queryKey: ["projects", workspaceId],
		queryFn: () => client.listProjects(workspaceId as string),
		enabled: !!workspaceId,
	});
	const projects =
		projectsQuery.data?.items.filter((item) => item.lifecycle === "Active") ??
		[];
	const projectId = params.get("projectId") ?? projects[0]?.projectId ?? null;
	const project = projects.find((item) => item.projectId === projectId) ?? null;
	const folderId = params.get("folderId");
	const trashMode = params.get("view") === "trash";
	const treeQuery = useQuery({
		queryKey: ["project-tree", projectId],
		queryFn: () => client.getProjectTree(projectId as string),
		enabled: !!projectId,
	});
	const resourcesQuery = useQuery({
		queryKey: ["resources", projectId],
		queryFn: () => client.listResources(projectId as string),
		enabled: !!projectId,
	});
	const projectTreeQueries = useQueries({
		queries: projects.map((item) => ({
			queryKey: ["project-tree", item.projectId],
			queryFn: () => client.getProjectTree(item.projectId),
		})),
	});
	const folderResourceEntries = projects.flatMap((item, projectIndex) =>
		(projectTreeQueries[projectIndex]?.data?.folders ?? [])
			.filter((folder) => folder.lifecycle === "Active")
			.map((folder) => ({
				projectId: item.projectId,
				folderId: folder.folderId,
			})),
	);
	const allResourcesQueries = useQueries({
		queries: projects.map((item) => ({
			queryKey: ["resources", item.projectId],
			queryFn: () => client.listResources(item.projectId),
		})),
	});
	const folderResourceQueries = useQueries({
		queries: folderResourceEntries.map(
			({ projectId: ownerId, folderId: id }) => ({
				queryKey: ["resources", ownerId, id],
				queryFn: () => client.listResources(ownerId, { folderId: id }),
			}),
		),
	});
	const allResources = [
		...allResourcesQueries.flatMap((query) => query.data?.items ?? []),
		...folderResourceQueries.flatMap((query) => query.data?.items ?? []),
	];
	const currentResources = folderId
		? folderResourceEntries.flatMap((entry, queryIndex) =>
				entry.projectId === projectId && entry.folderId === folderId
					? (folderResourceQueries[queryIndex]?.data?.items ?? [])
					: [],
			)
		: (resourcesQuery.data?.items ?? []);
	const visible = trashMode
		? allResources.filter((item) => item.lifecycle === "Trashed")
		: currentResources.filter(
				(item) =>
					item.lifecycle === "Active" && item.folderId === (folderId ?? null),
			);
	const activeFolder =
		treeQuery.data?.folders.find((item) => item.folderId === folderId) ?? null;

	function selectLocation(
		nextProjectId: string | null,
		nextFolderId: string | null = null,
		nextWorkspaceId: string | null = workspaceId,
	) {
		const next = new URLSearchParams(params);
		next.delete("view");
		if (nextWorkspaceId) next.set("workspaceId", nextWorkspaceId);
		else next.delete("workspaceId");
		if (nextProjectId) next.set("projectId", nextProjectId);
		else next.delete("projectId");
		if (nextFolderId) next.set("folderId", nextFolderId);
		else next.delete("folderId");
		setParams(next);
		setSidebarOpen(false);
	}
	async function completeLogout() {
		try {
			await client.logout();
			resourceRuntime.clearCachedAccountId();
			setLogoutDialogOpen(false);
			setLogoutDrafts(null);
			navigate("/login");
		} catch (error) {
			setLogoutError(error instanceof Error ? error.message : "退出登录失败。");
		}
	}

	async function logout() {
		setAccountMenu(false);
		setLogoutError("");
		setLogoutDialogOpen(true);
		const accountId = accountQuery.data?.accountId;
		if (!accountId) {
			await completeLogout();
			return;
		}
		setLogoutBusy(true);
		try {
			const drafts = await resourceRuntime.listUnsyncedResources(accountId);
			if (drafts.length === 0) {
				await completeLogout();
				return;
			}
			setLogoutDrafts(drafts);
		} catch (error) {
			setLogoutDrafts([]);
			setLogoutError(
				error instanceof Error
					? `无法检查本地未同步内容：${error.message}`
					: "无法检查本地未同步内容。请重试或取消退出。",
			);
		} finally {
			setLogoutBusy(false);
		}
	}

	async function exportDraftsAndLogout() {
		if (!logoutDrafts?.length) return;
		setLogoutBusy(true);
		setLogoutError("");
		try {
			downloadUnsyncedDrafts(logoutDrafts);
			await completeLogout();
		} catch (error) {
			setLogoutError(
				error instanceof Error ? error.message : "本地副本导出失败。",
			);
		} finally {
			setLogoutBusy(false);
		}
	}

	async function discardDraftsAndLogout() {
		const accountId = accountQuery.data?.accountId;
		if (!accountId || !logoutDrafts?.length) return;
		if (
			!window.confirm(
				"将删除此浏览器中列出的资源副本和未同步修改。服务器上已保存的内容不受影响。确定丢弃并退出吗？",
			)
		) {
			return;
		}
		setLogoutBusy(true);
		setLogoutError("");
		try {
			const currentDrafts =
				await resourceRuntime.listUnsyncedResources(accountId);
			for (const draft of currentDrafts) {
				await resourceRuntime.clearLocalResource(
					accountId,
					draft.resource.resourceId,
					{ confirmDiscardUnsyncedChanges: true },
				);
			}
			await completeLogout();
		} catch (error) {
			setLogoutError(
				error instanceof Error
					? `无法清除本地修改：${error.message}`
					: "无法清除本地修改；仍保留在此页面。",
			);
		} finally {
			setLogoutBusy(false);
		}
	}

	const projectResourceQueries = new Map(
		projects.map((item, index) => {
			const nestedResources = folderResourceEntries.flatMap(
				(entry, queryIndex) =>
					entry.projectId === item.projectId
						? (folderResourceQueries[queryIndex]?.data?.items ?? [])
						: [],
			);
			return [
				item.projectId,
				[
					...(allResourcesQueries[index]?.data?.items ?? []),
					...nestedResources,
				],
			];
		}),
	);
	const trashed = allResources.filter((item) => item.lifecycle === "Trashed");
	const loading =
		workspaceQuery.isLoading ||
		(!!workspaceId && projectsQuery.isLoading) ||
		(!!projectId && (treeQuery.isLoading || resourcesQuery.isLoading)) ||
		allResourcesQueries.some((query) => query.isLoading) ||
		projectTreeQueries.some((query) => query.isLoading) ||
		folderResourceQueries.some((query) => query.isLoading);
	const loadFailed =
		workspaceQuery.isError ||
		projectsQuery.isError ||
		resourcesQuery.isError ||
		treeQuery.isError ||
		allResourcesQueries.some((query) => query.isError) ||
		projectTreeQueries.some((query) => query.isError) ||
		folderResourceQueries.some((query) => query.isError);
	useEffect(() => {
		if (accountQuery.isSuccess && accountQuery.data === null) {
			navigate("/login", { replace: true });
		}
	}, [accountQuery.data, accountQuery.isSuccess, navigate]);
	return (
		<div className="app-stage console-shell" data-testid="console-shell">
			<div className="console-patchwork" aria-hidden="true">
				<span />
				<span />
				<span />
				<span />
				<span />
				<span />
			</div>
			<header className="console-topbar">
				<button
					type="button"
					className="mobile-sidebar-toggle"
					aria-label="打开导航"
					onClick={() => setSidebarOpen(true)}
				>
					<Icon name="menu" />
				</button>
				<div className="topbar-left">
					<div className="console-menu-anchor">
						<button
							type="button"
							className="ws-switcher-btn"
							data-testid="console-workspace-switcher"
							onClick={() => setWorkspaceMenu((value) => !value)}
						>
							<Icon name="workspace" />
							<span className="ws-name">{workspace?.name ?? "选择工作区"}</span>
							<span className="ws-role-pill">
								{workspace?.membershipKind ?? ""}
							</span>
						</button>
						{workspaceMenu && (
							<div className="console-dropdown">
								{workspaces.map((item: Workspace) => (
									<button
										key={item.workspaceId}
										type="button"
										className="console-dropdown-item"
										onClick={() => {
											selectLocation(null, null, item.workspaceId);
											setWorkspaceMenu(false);
										}}
									>
										{item.name}
									</button>
								))}
								<button
									type="button"
									className="console-dropdown-item"
									onClick={() => {
										setCreate({
											kind: "workspace",
											projectId: null,
											folderId: null,
										});
										setWorkspaceMenu(false);
									}}
								>
									＋ 新建工作区…
								</button>
							</div>
						)}
					</div>
					<SearchPalette
						workspaceId={workspaceId}
						onOpenResource={(id) =>
							navigate("/editor?resourceId=" + encodeURIComponent(id))
						}
					/>
				</div>
				<div className="topbar-right">
					<button
						type="button"
						className="btn-quiet"
						data-testid="open-task-center"
						onClick={() => navigate("/tasks")}
					>
						任务中心
					</button>
					<NotificationCenter
						onOpenResource={(id) =>
							navigate("/editor?resourceId=" + encodeURIComponent(id))
						}
					/>
					<div className="console-menu-anchor">
						<button
							type="button"
							className="icon-btn-quiet"
							aria-label="账号菜单"
							onClick={() => setAccountMenu((value) => !value)}
						>
							<Icon name="user" />
						</button>
						{accountMenu && (
							<div className="console-dropdown account-dropdown">
								<div className="console-account-email">
									{accountQuery.data?.primaryEmail ?? ""}
								</div>
								<button
									type="button"
									className="console-dropdown-item"
									data-testid="logout-button"
									onClick={() => void logout()}
								>
									退出登录
								</button>
							</div>
						)}
					</div>
					<span className="sr-only" data-testid="workspace-email">
						{accountQuery.data?.primaryEmail ?? ""}
					</span>
				</div>
			</header>
			<div className="console-body">
				{sidebarOpen && (
					<button
						type="button"
						className="mobile-sidebar-backdrop"
						aria-label="关闭导航"
						onClick={() => setSidebarOpen(false)}
					/>
				)}
				<aside
					className={"console-sidebar " + (sidebarOpen ? "mobile-open" : "")}
				>
					<div className="sidebar-heading">
						<span>项目</span>
						<button
							type="button"
							className="tree-add"
							aria-label="新建项目"
							onClick={() =>
								setCreate({ kind: "project", projectId: null, folderId: null })
							}
						>
							<Icon name="plus" />
						</button>
					</div>
					{projects.map((item: Project) => (
						<div
							key={item.projectId}
							data-testid={"console-tree-project-" + item.projectId}
						>
							<div
								className={
									"tree-node-row " +
									(projectId === item.projectId && !folderId ? "active" : "")
								}
							>
								<button
									type="button"
									className="tree-select"
									onClick={() => selectLocation(item.projectId)}
								>
									<Icon name="folder" />
									<span>{item.name}</span>
								</button>
								<button
									type="button"
									className="tree-add"
									aria-label={"在" + item.name + "中新建"}
									onClick={() =>
										setCreate({
											kind: "folder",
											projectId: item.projectId,
											folderId: null,
										})
									}
								>
									<Icon name="plus" />
								</button>
							</div>
							{projectId === item.projectId && (
								<FolderTree
									projectId={item.projectId}
									folders={treeQuery.data?.folders ?? []}
									resources={projectResourceQueries.get(item.projectId) ?? []}
									selectedFolderId={folderId}
									onSelect={(id) => selectLocation(item.projectId, id)}
									onOpen={(id) =>
										navigate("/editor?resourceId=" + encodeURIComponent(id))
									}
									onCreate={(kind, parent) =>
										setCreate({
											kind,
											projectId: item.projectId,
											folderId: parent,
										})
									}
								/>
							)}
							{projectId === item.projectId &&
								(projectResourceQueries.get(item.projectId) ?? [])
									.filter(
										(resource) =>
											resource.lifecycle === "Active" && !resource.folderId,
									)
									.map((resource) => (
										<button
											key={resource.resourceId}
											type="button"
											className="tree-resource-row"
											data-testid={`console-tree-resource-${resource.resourceId}`}
											onClick={() =>
												navigate(
													"/editor?resourceId=" +
														encodeURIComponent(resource.resourceId),
												)
											}
										>
											<ResourceIcon type={resource.resourceType} />
											<span>{resource.name}</span>
										</button>
									))}
						</div>
					))}
					{workspaceId && projects.length === 0 && (
						<div className="sidebar-empty">当前工作区暂无项目</div>
					)}
					<button
						type="button"
						className={"sidebar-trash-row " + (trashMode ? "active" : "")}
						onClick={() => {
							const next = new URLSearchParams(params);
							next.set("view", "trash");
							next.delete("folderId");
							setParams(next);
							setSidebarOpen(false);
						}}
					>
						<Icon name="trash" />
						<span>回收站</span>
						<span className="trash-count">{trashed.length || ""}</span>
					</button>
				</aside>
				<main className="console-main">
					<div className="content-header-row">
						<nav className="breadcrumb-trail" aria-label="当前位置">
							<button
								type="button"
								className="breadcrumb-item"
								onClick={() => selectLocation(null)}
							>
								{workspace?.name ?? "工作区"}
							</button>
							{project && !trashMode && (
								<>
									<span className="breadcrumb-sep">/</span>
									<button
										type="button"
										className={
											"breadcrumb-item " + (!activeFolder ? "current" : "")
										}
										onClick={() => selectLocation(project.projectId)}
									>
										{project.name}
									</button>
								</>
							)}
							{activeFolder && (
								<>
									<span className="breadcrumb-sep">/</span>
									<span className="breadcrumb-item current">
										{activeFolder.name}
									</span>
								</>
							)}
							{trashMode && (
								<>
									<span className="breadcrumb-sep">/</span>
									<span className="breadcrumb-item current">回收站</span>
								</>
							)}
						</nav>
						<div className="header-actions">
							{workspace && (
								<button
									type="button"
									className="btn-quiet"
									onClick={() => setMembersPanelOpen(true)}
								>
									成员与权限
								</button>
							)}
							{projects.length > 0 && !trashMode && (
								<>
									<button
										type="button"
										className="btn-quiet"
										onClick={() =>
											setCreate({ kind: "folder", projectId, folderId })
										}
									>
										<Icon name="folder" /> 新建文件夹
									</button>
									<button
										type="button"
										className="btn-create-context"
										onClick={() =>
											setCreate({ kind: "document", projectId, folderId })
										}
									>
										<Icon name="plus" /> 新建文档
									</button>
								</>
							)}
						</div>
					</div>
					{loading ? (
						<div className="console-loading">正在载入工作区…</div>
					) : loadFailed ? (
						<EmptyState
							title="服务暂时不可用"
							description="没能连上服务，请检查网络后重试。"
							action="重新加载"
							onAction={() => void cache.invalidateQueries()}
						/>
					) : workspaces.length === 0 ? (
						<EmptyState
							title="从一个工作区开始"
							description="创建你的第一个工作区，慢慢放入项目和文档。"
							action="创建工作区"
							onAction={() =>
								setCreate({
									kind: "workspace",
									projectId: null,
									folderId: null,
								})
							}
						/>
					) : projects.length === 0 ? (
						<EmptyState
							title="先建一个项目"
							description="把相近的文档放在同一个项目里。"
							action="新建项目"
							onAction={() =>
								setCreate({ kind: "project", projectId: null, folderId: null })
							}
						/>
					) : visible.length === 0 ? (
						<EmptyState
							title={trashMode ? "回收站是空的" : "这里还没有资源"}
							description={
								trashMode
									? "删除的资源会暂时保留在这里。"
									: "新建一份文档，先做点什么。"
							}
							action={trashMode ? undefined : "新建文档"}
							onAction={
								trashMode
									? undefined
									: () => setCreate({ kind: "document", projectId, folderId })
							}
							extra={
								!trashMode && (
									<button
										type="button"
										className="btn-quiet"
										onClick={() =>
											setCreate({ kind: "markdown", projectId, folderId })
										}
									>
										新建 Markdown
									</button>
								)
							}
						/>
					) : (
						<ResourceTable
							items={trashMode ? trashed : visible}
							trashMode={trashMode}
							open={(id) =>
								navigate("/editor?resourceId=" + encodeURIComponent(id))
							}
						/>
					)}
				</main>
			</div>
			{create && (
				<CreateDialog
					kind={create.kind}
					workspaceId={workspaceId}
					projectId={create.projectId}
					folderId={create.folderId}
					onClose={() => setCreate(null)}
				/>
			)}
			{membersPanelOpen && workspace && workspaceId && (
				<WorkspaceMembersPanel
					workspaceId={workspaceId}
					workspaceName={workspace.name}
					workspaceMembershipKind={workspace.membershipKind}
					projects={projects}
					currentAccountId={accountQuery.data?.accountId}
					onClose={() => setMembersPanelOpen(false)}
				/>
			)}
			{logoutDialogOpen && (
				<div className="console-modal-backdrop">
					<section
						className="console-modal"
						role="dialog"
						aria-modal="true"
						aria-labelledby="logout-recovery-title"
						data-testid="logout-recovery-dialog"
					>
						<h2 id="logout-recovery-title">退出前检查本地修改</h2>
						{logoutBusy && <p>正在检查或保存本地草稿…</p>}
						{logoutDrafts && logoutDrafts.length > 0 && (
							<>
								<p>
									有 {logoutDrafts.length}{" "}
									份文档包含尚未同步的修改。你可以先导出副本；
									丢弃操作只删除此设备上的本地副本。
								</p>
								<ul>
									{logoutDrafts.map((draft) => (
										<li key={draft.resource.resourceId}>
											{draft.resource.name}
										</li>
									))}
								</ul>
							</>
						)}
						{logoutError && (
							<p className="console-error" role="alert">
								{logoutError}
							</p>
						)}
						<div className="console-modal-actions">
							<button
								type="button"
								className="btn-quiet"
								disabled={logoutBusy}
								onClick={() => {
									setLogoutDialogOpen(false);
									setLogoutDrafts(null);
									setLogoutError("");
								}}
							>
								取消退出
							</button>
							{logoutDrafts && logoutDrafts.length > 0 && (
								<>
									<button
										type="button"
										className="btn-quiet"
										disabled={logoutBusy}
										onClick={() => void exportDraftsAndLogout()}
									>
										导出副本并退出
									</button>
									<button
										type="button"
										className="btn-quiet"
										disabled={logoutBusy}
										onClick={() => void discardDraftsAndLogout()}
									>
										丢弃本地修改并退出
									</button>
								</>
							)}
							{logoutError && !logoutDrafts?.length && (
								<button
									type="button"
									className="btn-quiet"
									disabled={logoutBusy}
									onClick={() => void logout()}
								>
									重新检查
								</button>
							)}
						</div>
					</section>
				</div>
			)}
		</div>
	);
}

function ResourceTable({
	items,
	trashMode,
	open,
}: {
	items: Resource[];
	trashMode: boolean;
	open(id: string): void;
}) {
	const cache = useQueryClient();
	const restore = useMutation({
		mutationFn: (resourceId: string) =>
			client.restoreResource(resourceId, {
				idempotencyKey: crypto.randomUUID(),
			}),
		onSuccess: () => cache.invalidateQueries(),
	});
	return (
		<div className="resource-list-container">
			<table className="resource-table">
				<thead>
					<tr>
						<th>资源名称</th>
						<th>类型</th>
						<th>生命周期</th>
					</tr>
				</thead>
				<tbody>
					{items.map((item) => (
						<tr
							key={item.resourceId}
							className="resource-row"
							data-testid="console-resource-row"
							onClick={() => {
								if (!trashMode) open(item.resourceId);
							}}
						>
							<td>
								<div className="resource-title-cell">
									<ResourceIcon type={item.resourceType} />
									<span className="resource-title-text">{item.name}</span>
									{trashMode && (
										<button
											type="button"
											className="trash-restore-button"
											data-testid={`trash-restore-${item.resourceId}`}
											disabled={restore.isPending}
											onClick={(event) => {
												event.stopPropagation();
												restore.mutate(item.resourceId);
											}}
										>
											恢复
										</button>
									)}
								</div>
							</td>
							<td>{item.resourceType}</td>
							<td>
								<span
									className={
										"lifecycle-badge " +
										(item.lifecycle === "Trashed" ? "trashed" : "")
									}
								>
									{item.lifecycle}
								</span>
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}
