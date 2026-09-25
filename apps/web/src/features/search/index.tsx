import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { client } from "../../shared/api/client";
import { ConsoleIcon, ResourceTypeIcon } from "../../shared/ui/console-icons";

type SearchItem = Awaited<
	ReturnType<typeof client.searchWorkspace>
>["items"][number];
type Folder = Awaited<
	ReturnType<typeof client.getProjectTree>
>["folders"][number];
type Project = Awaited<ReturnType<typeof client.listProjects>>["items"][number];

function resourceTypeLabel(type: SearchItem["resourceType"]): string {
	return {
		document: "文档",
		code: "代码",
		markdown: "Markdown",
		text: "文本",
	}[type];
}

function projectFolderPath(
	item: SearchItem,
	projects: Project[],
	trees: Array<{ projectId: string; folders: Folder[] }>,
): string {
	const project = projects.find(
		(candidate) => candidate.projectId === item.projectId,
	);
	const tree = trees.find(
		(candidate) => candidate.projectId === item.projectId,
	);
	const names: string[] = [];
	let current = tree?.folders.find(
		(folder) => folder.folderId === item.folderId,
	);
	while (current) {
		names.unshift(current.name);
		current = tree?.folders.find(
			(folder) => folder.folderId === current?.parentFolderId,
		);
	}
	return [project?.name, ...names].filter(Boolean).join(" / ");
}

export function SearchPalette({
	workspaceId,
	onOpenResource,
}: {
	workspaceId: string | null;
	onOpenResource(resourceId: string): void;
}) {
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState("");
	const [debounced, setDebounced] = useState("");
	const [activeIndex, setActiveIndex] = useState(0);
	useEffect(() => {
		const onKeyDown = (event: KeyboardEvent) => {
			if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
				event.preventDefault();
				setOpen(true);
			} else if (event.key === "Escape") {
				setOpen(false);
			}
		};
		window.addEventListener("keydown", onKeyDown);
		return () => window.removeEventListener("keydown", onKeyDown);
	}, []);
	useEffect(() => {
		const timer = window.setTimeout(() => setDebounced(query.trim()), 180);
		return () => window.clearTimeout(timer);
	}, [query]);
	const search = useQuery({
		queryKey: ["search", workspaceId, debounced],
		queryFn: () => client.searchWorkspace(workspaceId as string, debounced),
		enabled: open && !!workspaceId && debounced.length > 0,
	});
	const items = search.data?.items ?? [];
	const projectsQuery = useQuery({
		queryKey: ["projects", workspaceId],
		queryFn: () => client.listProjects(workspaceId as string),
		enabled: open && !!workspaceId,
	});
	const projectIds = useMemo(
		() => [
			...new Set(
				items.map((item) => item.projectId).filter((id): id is string => !!id),
			),
		],
		[items],
	);
	const treeQueries = useQueries({
		queries: projectIds.map((projectId) => ({
			queryKey: ["project-tree", projectId],
			queryFn: () => client.getProjectTree(projectId),
		})),
	});
	const trees = useMemo(
		() =>
			treeQueries.flatMap((query, index) =>
				query.data
					? [{ projectId: projectIds[index], folders: query.data.folders }]
					: [],
			),
		[projectIds, treeQueries],
	);
	const inputRef = (node: HTMLInputElement | null) => {
		if (node && open) queueMicrotask(() => node.focus());
	};

	function choose(item: SearchItem) {
		setOpen(false);
		setQuery("");
		onOpenResource(item.resourceId);
	}

	return (
		<>
			<button
				type="button"
				className="search-trigger-bar"
				data-testid="console-search-trigger"
				onClick={() => setOpen(true)}
			>
				<span className="search-trigger-icon" aria-hidden="true">
					<ConsoleIcon name="search" />
				</span>
				<span>搜索工作区资源…</span>
				<kbd className="search-shortcut-pill">⌘ K</kbd>
			</button>
			{open && (
				<div className="search-overlay">
					<section
						className="search-palette"
						role="dialog"
						aria-modal="true"
						aria-label="搜索工作区资源"
					>
						<div className="search-palette-input">
							<span className="search-palette-icon" aria-hidden="true">
								<ConsoleIcon name="search" size={18} />
							</span>
							<input
								ref={inputRef}
								value={query}
								onChange={(event) => {
									setQuery(event.target.value);
									setActiveIndex(0);
								}}
								onKeyDown={(event) => {
									if (event.key === "ArrowDown") {
										event.preventDefault();
										setActiveIndex((index) =>
											Math.min(items.length - 1, index + 1),
										);
									}
									if (event.key === "ArrowUp") {
										event.preventDefault();
										setActiveIndex((index) => Math.max(0, index - 1));
									}
									if (event.key === "Enter" && items[activeIndex]) {
										event.preventDefault();
										choose(items[activeIndex]);
									}
								}}
								placeholder="搜索名称或正文"
								aria-label="搜索名称或正文"
							/>
							<button
								type="button"
								onClick={() => setOpen(false)}
								aria-label="关闭搜索"
							>
								Esc
							</button>
						</div>
						{search.isFetching && <div className="search-state">正在搜索…</div>}
						{search.isError && (
							<div className="search-state" role="alert">
								搜索失败，请重试。
							</div>
						)}
						{debounced && !search.isFetching && !items.length && (
							<div className="search-state">没有找到匹配资源。</div>
						)}
						{items.length > 0 && (
							<ul className="search-results">
								{items.map((item, index) => (
									<li key={item.resourceId}>
										<button
											type="button"
											className={index === activeIndex ? "active" : ""}
											onMouseEnter={() => setActiveIndex(index)}
											onClick={() => choose(item)}
										>
											<ResourceTypeIcon type={item.resourceType} />
											<span className="search-result-copy">
												<strong>{item.name}</strong>
												<small>
													{projectFolderPath(
														item,
														projectsQuery.data?.items ?? [],
														trees,
													)}
												</small>
												{item.snippet && (
													<small className="search-snippet">
														{item.snippet}
													</small>
												)}
											</span>
											<span className="search-result-kind">
												{resourceTypeLabel(item.resourceType)}
											</span>
										</button>
									</li>
								))}
							</ul>
						)}
						<div className="search-palette-footer">
							<span>↑↓ 选择</span>
							<span>Enter 打开</span>
							<span>Esc 关闭</span>
						</div>
					</section>
				</div>
			)}
		</>
	);
}
