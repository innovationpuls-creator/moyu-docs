import {
	useMutation,
	useQueries,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { client } from "../../shared/api/client";
import { ConsoleIcon, ResourceTypeIcon } from "../../shared/ui/console-icons";
import { useShellUiStore } from "../../shared/ui-store";
import { NotificationCenter } from "../notifications";
import { SearchPalette } from "../search";

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

function resourceTypeLabel(type: ResourceType): string {
	return {
		document: "文档",
		code: "代码",
		markdown: "Markdown",
		text: "文本",
	}[type];
}

function lifecycleLabel(lifecycle: Resource["lifecycle"]): string {
	return {
		Active: "使用中",
		Trashed: "回收站",
		Purging: "正在清除",
		Purged: "已清除",
	}[lifecycle];
}

function membershipLabel(kind: string | undefined): string {
	if (kind === "Owner") return "所有者";
	if (kind === "Member") return "成员";
	return "";
}

function EmptyIllustration({
	variant,
}: {
	variant: "workspace" | "project" | "resource" | "trash" | "error";
}) {
	if (variant === "workspace") {
		return (
			<svg
				className="empty-illustration"
				viewBox="0 0 160 160"
				fill="none"
				aria-hidden="true"
			>
				<circle cx="80" cy="80" r="64" fill="var(--color-block-cream)" />
				<path
					d="M48 100c12-8 32-12 64-4s32 18 16 26-64 4-80-6 0-16 0-16z"
					fill="var(--color-block-peach)"
					opacity=".8"
				/>
				<circle
					cx="68"
					cy="62"
					r="14"
					fill="var(--color-block-sun)"
					opacity=".9"
				/>
				<path
					d="M80 50v24M70 62h20"
					stroke="var(--color-block-terracotta)"
					strokeWidth="2.5"
					strokeLinecap="round"
				/>
			</svg>
		);
	}
	if (variant === "project") {
		return (
			<svg
				className="empty-illustration"
				viewBox="0 0 160 160"
				fill="none"
				aria-hidden="true"
			>
				<rect
					x="36"
					y="44"
					width="88"
					height="72"
					rx="14"
					fill="var(--color-block-cream)"
					stroke="var(--border-card)"
					strokeWidth="2"
				/>
				<path
					d="M52 64h44M52 78h56M52 92h28"
					stroke="var(--color-block-terracotta)"
					strokeWidth="2"
					strokeLinecap="round"
					opacity=".6"
				/>
				<circle
					cx="110"
					cy="100"
					r="16"
					fill="var(--color-block-sage)"
					opacity=".85"
				/>
				<path
					d="M110 94v12M104 100h12"
					stroke="#fff"
					strokeWidth="2"
					strokeLinecap="round"
				/>
			</svg>
		);
	}
	if (variant === "resource") {
		return (
			<svg
				className="empty-illustration"
				viewBox="0 0 160 160"
				fill="none"
				aria-hidden="true"
			>
				<ellipse
					cx="80"
					cy="115"
					rx="50"
					ry="16"
					fill="var(--color-block-peach)"
					opacity=".5"
				/>
				<rect
					x="52"
					y="40"
					width="56"
					height="74"
					rx="8"
					fill="#fff"
					stroke="var(--border-card)"
					strokeWidth="2"
				/>
				<path
					d="M64 58h32M64 72h24M64 86h28"
					stroke="var(--ink-muted)"
					strokeWidth="2"
					strokeLinecap="round"
					opacity=".4"
				/>
				<circle cx="106" cy="46" r="10" fill="var(--color-block-sun)" />
			</svg>
		);
	}
	return (
		<span
			className={`empty-illustration empty-illustration-${variant}`}
			aria-hidden="true"
		>
			<ConsoleIcon
				name={variant === "trash" ? "trash" : "document"}
				size={32}
			/>
		</span>
	);
}

function EmptyState({
	variant,
	title,
	description,
	action,
	onAction,
	extra,
}: {
	variant: "workspace" | "project" | "resource" | "trash" | "error";
	title: string;
	description: string;
	action?: string;
	onAction?: () => void;
	extra?: React.ReactNode;
}) {
	return (
		<section
			className="console-empty-state"
			data-variant={variant}
			data-testid="console-empty-state"
		>
			<EmptyIllustration variant={variant} />
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
						aria-expanded={open}
						disabled={
							!folder.hasChildren &&
							childFolders.length === 0 &&
							childResources.length === 0
						}
						onClick={() =>
							setExpanded((old) => {
								const next = new Set(old);
								if (next.has(folder.folderId)) next.delete(folder.folderId);
								else next.add(folder.folderId);
								return next;
							})
						}
					>
						<ConsoleIcon name="chevron" />
					</button>
					<button
						type="button"
						className="tree-select"
						onClick={() => onSelect(folder.folderId)}
					>
						<ConsoleIcon name="folder" />
						<span>{folder.name}</span>
					</button>
					<button
						type="button"
						className="tree-add"
						aria-label={"在" + folder.name + "中新建"}
						onClick={() => onCreate("document", folder.folderId)}
					>
						<ConsoleIcon name="plus" />
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
								<ResourceTypeIcon type={resource.resourceType} />
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
	const [expandedProject, setExpandedProject] = useState<{
		projectId: string;
		open: boolean;
	} | null>(null);
	const sidebarOpen = useShellUiStore((state) => state.sidebarOpen);
	const setSidebarOpen = useShellUiStore((state) => state.setSidebarOpen);
	const [create, setCreate] = useState<{
		kind: CreateKind;
		projectId: string | null;
		folderId: string | null;
	} | null>(null);
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
		queryKey: ["resources", projectId, folderId],
		queryFn: () =>
			client.listResources(projectId as string, folderId ?? undefined),
		enabled: !!projectId,
	});
	const projectTreeQueries = useQueries({
		queries: projects.map((item) => ({
			queryKey: ["project-tree", item.projectId],
			queryFn: () => client.getProjectTree(item.projectId),
		})),
	});
	const allResourcesQueries = useQueries({
		queries: projects.map((item) => ({
			queryKey: ["resources", item.projectId],
			queryFn: () => client.listResources(item.projectId),
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
	const folderResourceQueries = useQueries({
		queries: folderResourceEntries.map(
			({ projectId: ownerId, folderId: id }) => ({
				queryKey: ["resources", ownerId, id],
				queryFn: () => client.listResources(ownerId, id),
			}),
		),
	});
	const allResources = [
		...allResourcesQueries.flatMap((query) => query.data?.items ?? []),
		...folderResourceQueries.flatMap((query) => query.data?.items ?? []),
	];
	const currentResources = resourcesQuery.data?.items ?? [];
	const visible = trashMode
		? allResources.filter((item) => item.lifecycle === "Trashed")
		: currentResources.filter(
				(item) =>
					item.lifecycle === "Active" && item.folderId === (folderId || null),
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
		setExpandedProject(
			nextProjectId ? { projectId: nextProjectId, open: true } : null,
		);
		setParams(next);
		setSidebarOpen(false);
	}
	async function logout() {
		try {
			await client.logout();
		} finally {
			navigate("/login");
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
	const fullWorkspaceEmpty =
		workspaceQuery.isSuccess && workspaces.length === 0 && !loadFailed;
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
			{!fullWorkspaceEmpty && (
				<header className="console-topbar">
					<button
						type="button"
						className="mobile-sidebar-toggle"
						aria-label="打开导航"
						onClick={() => setSidebarOpen(true)}
					>
						<ConsoleIcon name="menu" />
					</button>
					<div className="topbar-left">
						<div className="console-menu-anchor">
							<button
								type="button"
								className="ws-switcher-btn"
								data-testid="console-workspace-switcher"
								onClick={() => setWorkspaceMenu((value) => !value)}
							>
								<ConsoleIcon name="workspace" />
								<span className="ws-name">
									{workspace?.name ?? "选择工作区"}
								</span>
								<span className="ws-role-pill">
									{membershipLabel(workspace?.membershipKind)}
								</span>
								<ConsoleIcon name="chevronDown" size={13} />
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
										<ConsoleIcon name="plus" /> 新建工作区…
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
						<NotificationCenter
							onOpenResource={(id) =>
								navigate("/editor?resourceId=" + encodeURIComponent(id))
							}
						/>
						<div className="console-menu-anchor">
							<button
								type="button"
								className="account-menu-trigger"
								data-testid="console-account-menu"
								aria-label="账号菜单"
								aria-expanded={accountMenu}
								onClick={() => setAccountMenu((value) => !value)}
							>
								<span className="user-initial-badge">
									{accountQuery.data?.primaryEmail?.charAt(0).toUpperCase() ??
										""}
								</span>
								<span
									className="account-email-label"
									title={accountQuery.data?.primaryEmail ?? ""}
								>
									{accountQuery.data?.primaryEmail ?? ""}
								</span>
								<ConsoleIcon name="chevronDown" size={13} />
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
			)}
			<div
				className={
					"console-body " + (fullWorkspaceEmpty ? "workspace-empty-body" : "")
				}
			>
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
					hidden={fullWorkspaceEmpty}
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
							<ConsoleIcon name="plus" />
						</button>
					</div>
					{projects.map((item: Project, index) => {
						const itemResources =
							projectResourceQueries.get(item.projectId) ?? [];
						const itemFolders = projectTreeQueries[index]?.data?.folders ?? [];
						const projectExpanded = expandedProject
							? expandedProject.projectId === item.projectId &&
								expandedProject.open
							: projectId === item.projectId;
						const hasChildren =
							itemFolders.some((folder) => folder.lifecycle === "Active") ||
							itemResources.some((resource) => resource.lifecycle === "Active");
						return (
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
										className={
											"tree-disclosure " + (projectExpanded ? "expanded" : "")
										}
										aria-label={
											(projectExpanded ? "折叠 " : "展开 ") + item.name
										}
										aria-expanded={projectExpanded}
										disabled={!hasChildren}
										onClick={() =>
											setExpandedProject({
												projectId: item.projectId,
												open: !projectExpanded,
											})
										}
									>
										<ConsoleIcon name="chevron" size={13} />
									</button>
									<button
										type="button"
										className="tree-select"
										onClick={() => {
											setExpandedProject({
												projectId: item.projectId,
												open: true,
											});
											selectLocation(item.projectId);
										}}
									>
										<ConsoleIcon name="folder" />
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
										<ConsoleIcon name="plus" />
									</button>
								</div>
								{projectExpanded && (
									<FolderTree
										projectId={item.projectId}
										folders={itemFolders}
										resources={itemResources}
										selectedFolderId={folderId}
										onSelect={(id) => {
											setExpandedProject({
												projectId: item.projectId,
												open: true,
											});
											selectLocation(item.projectId, id);
										}}
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
								{projectExpanded &&
									itemResources
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
												<ResourceTypeIcon type={resource.resourceType} />
												<span>{resource.name}</span>
											</button>
										))}
							</div>
						);
					})}
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
						<ConsoleIcon name="trash" />
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
							{projects.length > 0 && !trashMode && (
								<>
									<button
										type="button"
										className="btn-quiet"
										onClick={() =>
											setCreate({ kind: "folder", projectId, folderId })
										}
									>
										<ConsoleIcon name="folder" /> 新建文件夹
									</button>
									<button
										type="button"
										className="btn-create-context"
										onClick={() =>
											setCreate({ kind: "document", projectId, folderId })
										}
									>
										<ConsoleIcon name="plus" /> 新建文档
									</button>
								</>
							)}
						</div>
					</div>
					{loading ? (
						<div className="console-loading">正在载入工作区…</div>
					) : loadFailed ? (
						<EmptyState
							variant="error"
							title="服务暂时不可用"
							description="没能连上服务，请检查网络后重试。"
							action="重新加载"
							onAction={() => void cache.invalidateQueries()}
						/>
					) : workspaces.length === 0 ? (
						<EmptyState
							variant="workspace"
							title="还没有属于你的工作区"
							description="从一个工作区开始，把项目和文档安放在这里。"
							action="创建第一个工作区"
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
							variant="project"
							title="当前工作区暂无项目"
							description="先建一个项目，把相关文档放在一起。"
							action="新建项目"
							onAction={() =>
								setCreate({ kind: "project", projectId: null, folderId: null })
							}
						/>
					) : visible.length === 0 ? (
						<EmptyState
							variant={trashMode ? "trash" : "resource"}
							title={trashMode ? "回收站是空的" : "这里还没有资源"}
							description={
								trashMode
									? "移入回收站的资源会显示在这里。"
									: "这里还没有资源。从一份文档开始，把想法和资料放进这个项目。"
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
									<ResourceTypeIcon type={item.resourceType} />
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
							<td>{resourceTypeLabel(item.resourceType)}</td>
							<td>
								<span
									className={
										"lifecycle-badge " +
										(item.lifecycle === "Trashed" ? "trashed" : "")
									}
								>
									{lifecycleLabel(item.lifecycle)}
								</span>
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}
