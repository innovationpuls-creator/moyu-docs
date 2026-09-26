import type { ProjectPermissionRole } from "@dom/client-sdk";
import {
	useMutation,
	useQueries,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client } from "../../shared/api/client";
import "./members-panel.css";

type Scope = "workspace" | "project" | "resource";
type ProjectRole = ProjectPermissionRole;
type Project = Awaited<ReturnType<typeof client.listProjects>>["items"][number];
type WorkspaceMember = Awaited<
	ReturnType<typeof client.listWorkspaceMembers>
>["members"][number];
type WorkspaceAccount = {
	accountId: string;
	email: string;
	membershipKind?: "Owner" | "Member";
};
type ProjectRoleRow = {
	accountId: string;
	email: string;
	role: ProjectRole | "";
	membershipKind?: "Owner" | "Member";
	isWorkspaceMember?: boolean;
};
type ResourceRoleRow = {
	accountId: string;
	email: string;
	role: ProjectRole | "";
};
type ProjectFolder = Awaited<
	ReturnType<typeof client.getProjectTree>
>["folders"][number];

const projectRoles: ProjectRole[] = ["Manage", "Edit", "Comment", "Read"];
const resourceRoles: ProjectRole[] = ["Manage", "Edit", "Comment", "Read"];

function errorText(error: unknown): string {
	return error instanceof Error ? error.message : "操作失败，请重试。";
}

function formatDate(value: string): string {
	return new Intl.DateTimeFormat("zh-CN", {
		dateStyle: "medium",
		timeStyle: "short",
	}).format(new Date(value));
}

export function WorkspaceMembersPanel({
	workspaceId,
	workspaceName,
	workspaceMembershipKind,
	projects,
	currentAccountId,
	onClose,
}: {
	workspaceId: string;
	workspaceName: string;
	workspaceMembershipKind: "Owner" | "Member";
	projects: Project[];
	currentAccountId: string | undefined;
	onClose(): void;
}) {
	const cache = useQueryClient();
	const [scope, setScope] = useState<Scope>("workspace");
	const [targetEmail, setTargetEmail] = useState("");
	const [expiresInDays, setExpiresInDays] = useState(7);
	const [inviteUrl, setInviteUrl] = useState<string | null>(null);
	const [inviteStatus, setInviteStatus] = useState<string | null>(null);
	const [copyError, setCopyError] = useState<string | null>(null);
	const [selectedProjectId, setSelectedProjectId] = useState(
		projects[0]?.projectId ?? "",
	);
	const [selectedResourceId, setSelectedResourceId] = useState("");
	const [memberSearchDraft, setMemberSearchDraft] = useState("");
	const [memberSearch, setMemberSearch] = useState("");
	useEffect(() => {
		const timer = window.setTimeout(
			() => setMemberSearch(memberSearchDraft.trim()),
			250,
		);
		return () => window.clearTimeout(timer);
	}, [memberSearchDraft]);
	const membersQuery = useQuery({
		queryKey: ["workspace-members", workspaceId],
		queryFn: () => client.listWorkspaceMembers(workspaceId),
		enabled: scope === "workspace" && workspaceMembershipKind === "Owner",
	});
	const invitationsQuery = useQuery({
		queryKey: ["workspace-invitations", workspaceId],
		queryFn: () => client.listWorkspaceInvitations(workspaceId),
		enabled: scope === "workspace" && workspaceMembershipKind === "Owner",
	});
	const projectMembersQuery = useQuery({
		queryKey: ["project-members", selectedProjectId],
		queryFn: () => client.listProjectMembers(selectedProjectId),
		enabled:
			(scope === "project" || scope === "resource") && selectedProjectId !== "",
	});
	const memberSuggestionsQuery = useQuery({
		queryKey: ["workspace-member-suggestions", workspaceId, memberSearch],
		queryFn: () => client.suggestMembers(workspaceId, memberSearch),
		enabled:
			(scope === "project" || scope === "resource") && memberSearch.length > 0,
	});
	const projectResourcesQuery = useQuery({
		queryKey: ["resources", selectedProjectId],
		queryFn: () => client.listResources(selectedProjectId),
		enabled: scope === "resource" && selectedProjectId !== "",
	});
	const projectTreeQuery = useQuery({
		queryKey: ["project-tree", selectedProjectId],
		queryFn: () => client.getProjectTree(selectedProjectId),
		enabled: scope === "resource" && selectedProjectId !== "",
	});
	const folderResourcesQueries = useQueries({
		queries: (projectTreeQuery.data?.folders ?? [])
			.filter((folder) => folder.lifecycle === "Active")
			.map((folder) => ({
				queryKey: ["resources", selectedProjectId, folder.folderId],
				queryFn: () =>
					client.listResources(selectedProjectId, {
						folderId: folder.folderId,
					}),
				enabled: scope === "resource" && selectedProjectId !== "",
			})),
	});
	const resources = [
		...(projectResourcesQuery.data?.items ?? []),
		...folderResourcesQueries.flatMap((query) => query.data?.items ?? []),
	].filter((resource) => resource.lifecycle === "Active");
	const resourceId = resources.some(
		(resource) => resource.resourceId === selectedResourceId,
	)
		? selectedResourceId
		: "";
	const folderPaths = getFolderPaths(projectTreeQuery.data?.folders ?? []);
	const resourcePermissionsQuery = useQuery({
		queryKey: ["resource-permissions", resourceId],
		queryFn: () => client.listResourcePermissions(resourceId),
		enabled: scope === "resource" && resourceId !== "",
	});
	const createInvitation = useMutation({
		mutationFn: () =>
			client.createWorkspaceInvitation(workspaceId, {
				targetEmail: targetEmail.trim(),
				expiresInDays,
			}),
		onSuccess: async (result) => {
			setInviteUrl(new URL(result.invitationUrl, window.location.origin).href);
			setInviteStatus(
				result.notificationSent
					? "已向对方发送站内邀请；对方接受后你会收到通知。"
					: "邀请链接已生成。请复制并发送给对方；对方接受后你会收到通知。",
			);
			setCopyError(null);
			await cache.invalidateQueries({
				queryKey: ["workspace-invitations", workspaceId],
			});
			await cache.invalidateQueries({ queryKey: ["notifications"] });
		},
	});
	const revokeInvitation = useMutation({
		mutationFn: (invitationId: string) =>
			client.revokeWorkspaceInvitation(workspaceId, invitationId),
		onSuccess: () =>
			cache.invalidateQueries({
				queryKey: ["workspace-invitations", workspaceId],
			}),
	});
	const removeWorkspaceMember = useMutation({
		mutationFn: (accountId: string) =>
			client.removeWorkspaceMember(workspaceId, accountId),
		onSuccess: () =>
			cache.invalidateQueries({ queryKey: ["workspace-members", workspaceId] }),
	});
	const setProjectRole = useMutation({
		mutationFn: ({
			accountId,
			role,
		}: {
			accountId: string;
			role: ProjectRole;
		}) => client.setProjectMemberRole(selectedProjectId, accountId, role),
		onSuccess: () =>
			cache.invalidateQueries({
				queryKey: ["project-members", selectedProjectId],
			}),
	});
	const removeProjectRole = useMutation({
		mutationFn: (accountId: string) =>
			client.removeProjectMember(selectedProjectId, accountId),
		onSuccess: () =>
			cache.invalidateQueries({
				queryKey: ["project-members", selectedProjectId],
			}),
	});
	const setResourceRole = useMutation({
		mutationFn: ({
			accountId,
			role,
		}: {
			accountId: string;
			role: ProjectRole;
		}) => client.setResourcePermission(resourceId, accountId, role),
		onSuccess: () =>
			cache.invalidateQueries({
				queryKey: ["resource-permissions", resourceId],
			}),
	});
	const removeResourceRole = useMutation({
		mutationFn: (accountId: string) =>
			client.removeResourcePermission(resourceId, accountId),
		onSuccess: () =>
			cache.invalidateQueries({
				queryKey: ["resource-permissions", resourceId],
			}),
	});
	const workspaceMembers = membersQuery.data?.members ?? [];
	const projectMembers = projectMembersQuery.data?.members ?? [];
	const resourcePermissions = resourcePermissionsQuery.data?.permissions ?? [];
	const workspaceAccounts: WorkspaceAccount[] =
		workspaceMembers.length > 0
			? workspaceMembers
			: (memberSuggestionsQuery.data?.suggestions ?? []);
	const projectManagers = new Set(
		projectMembers
			.filter((member) => member.role === "Owner" || member.role === "Manage")
			.map((member) => member.accountId),
	);
	const canManageProject =
		workspaceMembershipKind === "Owner" ||
		projectManagers.has(currentAccountId ?? "");
	const canGrantProjectOwner = projectMembers.some(
		(member) =>
			member.accountId === currentAccountId && member.role === "Owner",
	);
	const projectOwnerCount = projectMembers.filter(
		(member) => member.role === "Owner",
	).length;
	const canManageResource =
		canManageProject ||
		resourcePermissions.some(
			(permission) =>
				permission.accountId === currentAccountId &&
				(permission.role === "Owner" || permission.role === "Manage"),
		);
	const projectRows = mergeMembersAndRoles(workspaceAccounts, projectMembers);
	const resourceRows = mergeMembersAndPermissions(
		workspaceAccounts,
		resourcePermissions,
	);
	const pending =
		createInvitation.isPending ||
		revokeInvitation.isPending ||
		removeWorkspaceMember.isPending ||
		setProjectRole.isPending ||
		removeProjectRole.isPending ||
		setResourceRole.isPending ||
		removeResourceRole.isPending;

	async function copyInviteLink() {
		if (!inviteUrl) return;
		try {
			await navigator.clipboard.writeText(inviteUrl);
			setCopyError(null);
		} catch (error) {
			setCopyError(
				navigator.clipboard
					? `浏览器拒绝了自动复制（${errorText(error)}）。请点击链接框，按 Ctrl+A 后 Ctrl+C。`
					: "当前网页不支持自动复制。请点击链接框，按 Ctrl+A 后 Ctrl+C。",
			);
		}
	}

	function onProjectRoleChange(accountId: string, value: string) {
		if (value === "") {
			removeProjectRole.mutate(accountId);
			return;
		}
		setProjectRole.mutate({ accountId, role: value as ProjectRole });
	}

	function onResourceRoleChange(accountId: string, value: string) {
		if (value === "") {
			removeResourceRole.mutate(accountId);
			return;
		}
		setResourceRole.mutate({ accountId, role: value as ProjectRole });
	}

	return (
		<div className="members-backdrop">
			<section
				className="members-panel"
				role="dialog"
				aria-modal="true"
				aria-labelledby="members-panel-title"
				onMouseDown={(event) => event.stopPropagation()}
			>
				<header className="members-panel-header">
					<div>
						<p className="members-eyebrow">WORKSPACE ACCESS</p>
						<h2 id="members-panel-title">{workspaceName} · 成员与权限</h2>
					</div>
					<button
						type="button"
						className="members-close"
						aria-label="关闭成员管理"
						onClick={onClose}
					>
						×
					</button>
				</header>
				<nav className="members-tabs" aria-label="权限范围">
					<button
						type="button"
						className={scope === "workspace" ? "active" : ""}
						aria-pressed={scope === "workspace"}
						onClick={() => setScope("workspace")}
					>
						工作区成员
					</button>
					<button
						type="button"
						className={scope === "project" ? "active" : ""}
						aria-pressed={scope === "project"}
						onClick={() => setScope("project")}
					>
						项目角色
					</button>
					<button
						type="button"
						className={scope === "resource" ? "active" : ""}
						aria-pressed={scope === "resource"}
						onClick={() => setScope("resource")}
					>
						单文档覆盖
					</button>
				</nav>
				<div className="members-panel-content">
					{scope === "workspace" && (
						<WorkspaceScope
							canManage={workspaceMembershipKind === "Owner"}
							members={workspaceMembers}
							invitations={invitationsQuery.data?.invitations ?? []}
							currentAccountId={currentAccountId}
							targetEmail={targetEmail}
							setTargetEmail={setTargetEmail}
							expiresInDays={expiresInDays}
							setExpiresInDays={setExpiresInDays}
							inviteUrl={inviteUrl}
							inviteStatus={inviteStatus}
							copyError={copyError}
							copyInviteLink={() => void copyInviteLink()}
							creating={createInvitation.isPending}
							mutating={pending}
							onCreate={() => createInvitation.mutate()}
							onRevoke={(id) => revokeInvitation.mutate(id)}
							onRemove={(accountId) => {
								if (
									window.confirm(
										"移除此工作区成员？其独立项目和文档权限不会自动改变。",
									)
								)
									removeWorkspaceMember.mutate(accountId);
							}}
							loading={membersQuery.isLoading || invitationsQuery.isLoading}
							error={
								membersQuery.error ??
								invitationsQuery.error ??
								createInvitation.error ??
								revokeInvitation.error ??
								removeWorkspaceMember.error
							}
						/>
					)}
					{scope === "project" && (
						<ProjectScope
							projects={projects}
							selectedProjectId={selectedProjectId}
							setSelectedProjectId={setSelectedProjectId}
							memberSearch={memberSearchDraft}
							setMemberSearch={setMemberSearchDraft}
							memberSearchLoading={memberSuggestionsQuery.isFetching}
							rows={projectRows}
							canManage={canManageProject}
							canGrantOwner={canGrantProjectOwner}
							projectOwnerCount={projectOwnerCount}
							loading={projectMembersQuery.isLoading}
							onRoleChange={onProjectRoleChange}
							error={
								projectMembersQuery.error ??
								memberSuggestionsQuery.error ??
								setProjectRole.error ??
								removeProjectRole.error
							}
						/>
					)}
					{scope === "resource" && (
						<ResourceScope
							projects={projects}
							selectedProjectId={selectedProjectId}
							setSelectedProjectId={setSelectedProjectId}
							memberSearch={memberSearchDraft}
							setMemberSearch={setMemberSearchDraft}
							memberSearchLoading={memberSuggestionsQuery.isFetching}
							resources={resources}
							folderPaths={folderPaths}
							selectedResourceId={resourceId}
							setSelectedResourceId={setSelectedResourceId}
							rows={resourceRows}
							canManage={canManageResource}
							loading={
								projectResourcesQuery.isLoading ||
								projectTreeQuery.isLoading ||
								folderResourcesQueries.some((query) => query.isLoading) ||
								resourcePermissionsQuery.isLoading
							}
							onRoleChange={onResourceRoleChange}
							error={
								projectResourcesQuery.error ??
								projectTreeQuery.error ??
								folderResourcesQueries.find((query) => query.error)?.error ??
								memberSuggestionsQuery.error ??
								resourcePermissionsQuery.error ??
								setResourceRole.error ??
								removeResourceRole.error
							}
						/>
					)}
				</div>
				{pending && (
					<span className="sr-only" role="status">
						正在保存权限变更
					</span>
				)}
			</section>
		</div>
	);
}

function WorkspaceScope({
	canManage,
	members,
	invitations,
	currentAccountId,
	targetEmail,
	setTargetEmail,
	expiresInDays,
	setExpiresInDays,
	inviteUrl,
	inviteStatus,
	copyError,
	copyInviteLink,
	creating,
	mutating,
	onCreate,
	onRevoke,
	onRemove,
	loading,
	error,
}: {
	canManage: boolean;
	members: WorkspaceMember[];
	invitations: Awaited<
		ReturnType<typeof client.listWorkspaceInvitations>
	>["invitations"];
	currentAccountId: string | undefined;
	targetEmail: string;
	setTargetEmail(value: string): void;
	expiresInDays: number;
	setExpiresInDays(value: number): void;
	inviteUrl: string | null;
	inviteStatus: string | null;
	copyError: string | null;
	copyInviteLink(): void;
	creating: boolean;
	mutating: boolean;
	onCreate(): void;
	onRevoke(id: string): void;
	onRemove(accountId: string): void;
	loading: boolean;
	error: unknown;
}) {
	return (
		<div className="members-scope">
			<div className="members-intro">
				<div>
					<h3>工作区成员</h3>
					<p>邀请只加入工作区。项目角色和单文档覆盖需要在各自范围单独授予。</p>
				</div>
				<span className="members-count">{members.length} 位成员</span>
			</div>
			{!canManage ? (
				<p className="members-note">
					工作区成员和邀请仅工作区 Owner
					可查看或管理。项目与文档权限仍可在各自范围单独配置。
				</p>
			) : (
				<>
					<form
						className="invite-form"
						onSubmit={(event) => {
							event.preventDefault();
							onCreate();
						}}
					>
						<label>
							<span>邀请邮箱</span>
							<input
								type="email"
								value={targetEmail}
								required
								autoComplete="email"
								placeholder="name@company.com"
								onChange={(event) => setTargetEmail(event.target.value)}
							/>
						</label>
						<label className="invite-expiry">
							<span>有效期</span>
							<select
								value={expiresInDays}
								onChange={(event) =>
									setExpiresInDays(Number(event.target.value))
								}
							>
								<option value={7}>7 天</option>
								<option value={14}>14 天</option>
								<option value={30}>30 天</option>
							</select>
						</label>
						<button
							className="members-primary-button"
							type="submit"
							disabled={creating}
						>
							{creating ? "正在创建…" : "生成邀请链接"}
						</button>
					</form>
					{inviteUrl && (
						<div className="invite-link-card" role="status">
							{inviteStatus && <p>{inviteStatus}</p>}
							<div>
								<strong>邀请链接已生成</strong>
								<p>
									请使用目标邮箱对应的账号接受邀请；已注册账号可直接在通知中加入，接受后你会收到反馈。
								</p>
							</div>
							<div className="invite-link-row">
								<input aria-label="邀请链接" readOnly value={inviteUrl} />
								<button type="button" onClick={copyInviteLink}>
									复制
								</button>
							</div>
							{copyError && (
								<p className="members-error">复制失败：{copyError}</p>
							)}
						</div>
					)}
					{error !== null && error !== undefined && (
						<p className="members-error">{errorText(error)}</p>
					)}
					<section className="members-list-section">
						<h4>成员</h4>
						{loading ? (
							<p className="members-muted">正在读取成员…</p>
						) : members.length === 0 ? (
							<p className="members-muted">目前没有成员。</p>
						) : (
							<ul className="members-list">
								{members.map((member) => (
									<li key={member.accountId}>
										<div className="member-identity">
											<span className="member-avatar">
												{member.email.slice(0, 1).toUpperCase()}
											</span>
											<span>
												<strong>{member.email}</strong>
												<small>加入于 {formatDate(member.createdAt)}</small>
											</span>
										</div>
										<span
											className={
												"member-kind " +
												(member.membershipKind === "Owner" ? "owner" : "")
											}
										>
											{member.membershipKind === "Owner"
												? "工作区所有者"
												: "工作区成员"}
										</span>
										{member.membershipKind === "Owner" ||
										member.accountId === currentAccountId ? (
											<span className="members-muted member-protected">
												受保护
											</span>
										) : (
											<button
												type="button"
												className="members-text-button danger"
												onClick={() => onRemove(member.accountId)}
											>
												移除
											</button>
										)}
									</li>
								))}
							</ul>
						)}
					</section>
					<section className="members-list-section">
						<h4>邀请记录</h4>
						{invitations.length === 0 ? (
							<p className="members-muted">尚无邀请。</p>
						) : (
							<ul className="members-list invitation-list">
								{invitations.map((invitation) => (
									<li key={invitation.invitationId}>
										<div className="member-identity invitation-identity">
											<span className="member-avatar invite-avatar">↗</span>
											<span>
												<strong>{invitation.targetEmail}</strong>
												<small>到期于 {formatDate(invitation.expiresAt)}</small>
											</span>
										</div>
										<span
											className={
												"invitation-state state-" +
												invitation.state.toLowerCase()
											}
										>
											{invitationState(invitation.state)}
										</span>
										{invitation.state === "Pending" && (
											<button
												type="button"
												className="members-text-button danger"
												disabled={mutating}
												onClick={() => onRevoke(invitation.invitationId)}
											>
												撤销
											</button>
										)}
										{invitation.state !== "Accepted" && (
											<button
												type="button"
												className="members-text-button"
												onClick={() => setTargetEmail(invitation.targetEmail)}
											>
												重新生成链接
											</button>
										)}
									</li>
								))}
							</ul>
						)}
						<p className="members-muted invitation-footnote">
							邀请链接只在创建时返回。刷新后无法再次读取旧链接，可为对应邮箱重新生成。
						</p>
					</section>
				</>
			)}
		</div>
	);
}

function ProjectScope({
	projects,
	selectedProjectId,
	setSelectedProjectId,
	memberSearch,
	setMemberSearch,
	memberSearchLoading,
	rows,
	canManage,
	canGrantOwner,
	projectOwnerCount,
	loading,
	onRoleChange,
	error,
}: {
	projects: Project[];
	selectedProjectId: string;
	setSelectedProjectId(value: string): void;
	memberSearch: string;
	setMemberSearch(value: string): void;
	memberSearchLoading: boolean;
	rows: ProjectRoleRow[];
	canManage: boolean;
	canGrantOwner: boolean;
	projectOwnerCount: number;
	loading: boolean;
	onRoleChange(accountId: string, value: string): void;
	error: unknown;
}) {
	return (
		<div className="members-scope">
			<div className="members-intro">
				<div>
					<h3>项目角色</h3>
					<p>
						只授予所选项目的直接角色；工作区成员身份本身不会获得项目访问权。
					</p>
				</div>
			</div>
			{projects.length > 0 ? (
				<label className="scope-select">
					<span>项目</span>
					<select
						value={selectedProjectId}
						onChange={(event) => setSelectedProjectId(event.target.value)}
					>
						{projects.map((project) => (
							<option key={project.projectId} value={project.projectId}>
								{project.name}
							</option>
						))}
					</select>
				</label>
			) : (
				<p className="members-muted">当前工作区还没有项目。</p>
			)}
			<label className="scope-select member-search">
				<span>查找工作区成员 {memberSearchLoading ? "· 搜索中" : ""}</span>
				<input
					type="search"
					value={memberSearch}
					placeholder="输入邮箱片段"
					onChange={(event) => setMemberSearch(event.target.value)}
				/>
			</label>
			{!canManage && (
				<p className="members-note">
					当前账号没有可确认的项目 Manage/Owner
					角色，服务端会按项目权限拒绝未授权的修改。
				</p>
			)}
			{error !== null && error !== undefined && (
				<p className="members-error">{errorText(error)}</p>
			)}
			{loading ? (
				<p className="members-muted">正在读取项目角色…</p>
			) : rows.length === 0 ? (
				<p className="members-muted">
					{memberSearch.trim()
						? "未找到匹配成员或直接项目授权。"
						: "输入邮箱搜索工作区成员，或查看已有的直接项目授权。"}
				</p>
			) : (
				<ul className="members-list scoped-roles-list">
					{rows.map((row) => (
						<li key={row.accountId}>
							<div className="member-identity">
								<span className="member-avatar">
									{row.email.slice(0, 1).toUpperCase()}
								</span>
								<span>
									<strong>{row.email}</strong>
									<small>
										{row.isWorkspaceMember ? "工作区成员" : "项目授权对象"}
									</small>
								</span>
							</div>
							{row.role === "Owner" &&
							(!canGrantOwner || projectOwnerCount <= 1) ? (
								<span className="member-kind owner">项目所有者</span>
							) : (
								<select
									aria-label={`为 ${row.email} 设置项目角色`}
									disabled={!canManage}
									value={row.role}
									onChange={(event) =>
										onRoleChange(row.accountId, event.target.value)
									}
								>
									<option value="">无直接角色</option>
									{canGrantOwner && <option value="Owner">项目所有者</option>}
									{projectRoles.map((role) => (
										<option key={role} value={role}>
											{projectRoleLabel(role)}
										</option>
									))}
								</select>
							)}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

function ResourceScope({
	projects,
	selectedProjectId,
	setSelectedProjectId,
	memberSearch,
	setMemberSearch,
	memberSearchLoading,
	resources,
	folderPaths,
	selectedResourceId,
	setSelectedResourceId,
	rows,
	canManage,
	loading,
	onRoleChange,
	error,
}: {
	projects: Project[];
	selectedProjectId: string;
	setSelectedProjectId(value: string): void;
	memberSearch: string;
	setMemberSearch(value: string): void;
	memberSearchLoading: boolean;
	resources: Awaited<ReturnType<typeof client.listResources>>["items"];
	folderPaths: Map<string, string>;
	selectedResourceId: string;
	setSelectedResourceId(value: string): void;
	rows: ResourceRoleRow[];
	canManage: boolean;
	loading: boolean;
	onRoleChange(accountId: string, value: string): void;
	error: unknown;
}) {
	return (
		<div className="members-scope">
			<div className="members-intro">
				<div>
					<h3>单文档权限覆盖</h3>
					<p>此处只管理所选文档的自定义覆盖，不修改工作区成员或项目角色。</p>
				</div>
			</div>
			<label className="scope-select member-search">
				<span>查找工作区成员 {memberSearchLoading ? "· 搜索中" : ""}</span>
				<input
					type="search"
					value={memberSearch}
					placeholder="输入邮箱片段"
					onChange={(event) => setMemberSearch(event.target.value)}
				/>
			</label>
			<div className="scope-select-row">
				<label className="scope-select">
					<span>项目</span>
					<select
						value={selectedProjectId}
						onChange={(event) => {
							setSelectedProjectId(event.target.value);
							setSelectedResourceId("");
						}}
					>
						{projects.map((project) => (
							<option key={project.projectId} value={project.projectId}>
								{project.name}
							</option>
						))}
					</select>
				</label>
				<label className="scope-select">
					<span>文档</span>
					<select
						value={selectedResourceId}
						onChange={(event) => setSelectedResourceId(event.target.value)}
					>
						<option value="">请选择文档</option>
						{resources.map((resource) => (
							<option key={resource.resourceId} value={resource.resourceId}>
								{resource.name} ·{" "}
								{resource.folderId
									? (folderPaths.get(resource.folderId) ?? "项目文件夹")
									: "项目根目录"}
							</option>
						))}
					</select>
				</label>
			</div>
			{resources.length === 0 && (
				<p className="members-muted">所选项目没有可配置的活动文档。</p>
			)}
			{!canManage && selectedResourceId !== "" && (
				<p className="members-note">
					当前账号没有确认到此项目或文档的 Manage/Owner 授权；下拉框已锁定。
				</p>
			)}
			{error !== null && error !== undefined && (
				<p className="members-error">{errorText(error)}</p>
			)}
			{loading ? (
				<p className="members-muted">正在读取文档覆盖…</p>
			) : rows.length === 0 ? (
				<p className="members-muted">
					{selectedResourceId === ""
						? "请选择文档查看或调整权限覆盖。"
						: memberSearch.trim()
							? "未找到匹配成员或自定义覆盖。"
							: "输入邮箱搜索工作区成员，或查看已有的文档权限覆盖。"}
				</p>
			) : (
				<ul className="members-list scoped-roles-list">
					{rows.map((row) => (
						<li key={row.accountId}>
							<div className="member-identity">
								<span className="member-avatar">
									{row.email.slice(0, 1).toUpperCase()}
								</span>
								<span>
									<strong>{row.email}</strong>
									<small>单文档权限覆盖</small>
								</span>
							</div>
							{row.role === "Owner" ? (
								<span className="member-kind owner">文档所有者</span>
							) : (
								<select
									aria-label={`为 ${row.email} 设置文档角色`}
									disabled={!canManage}
									value={row.role}
									onChange={(event) =>
										onRoleChange(row.accountId, event.target.value)
									}
								>
									<option value="">无覆盖</option>
									{resourceRoles.map((role) => (
										<option key={role} value={role}>
											{projectRoleLabel(role)}
										</option>
									))}
								</select>
							)}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

function mergeMembersAndRoles(
	members: WorkspaceAccount[],
	roles: Awaited<ReturnType<typeof client.listProjectMembers>>["members"],
): ProjectRoleRow[] {
	const rows = new Map<string, ProjectRoleRow>();
	for (const role of roles)
		rows.set(role.accountId, { ...role, isWorkspaceMember: false });
	for (const member of members) {
		const existing = rows.get(member.accountId);
		if (existing) {
			rows.set(member.accountId, { ...existing, isWorkspaceMember: true });
		} else {
			rows.set(member.accountId, {
				accountId: member.accountId,
				email: member.email,
				role: "" as const,
				membershipKind: member.membershipKind,
				isWorkspaceMember: true,
			});
		}
	}
	return [...rows.values()].sort((a, b) => a.email.localeCompare(b.email));
}

function mergeMembersAndPermissions(
	members: WorkspaceAccount[],
	permissions: Awaited<
		ReturnType<typeof client.listResourcePermissions>
	>["permissions"],
): ResourceRoleRow[] {
	const rows = new Map<string, ResourceRoleRow>();
	for (const permission of permissions)
		rows.set(permission.accountId, { ...permission });
	for (const member of members) {
		if (!rows.has(member.accountId)) {
			rows.set(member.accountId, {
				accountId: member.accountId,
				email: member.email,
				role: "" as const,
			});
		}
	}
	return [...rows.values()].sort((a, b) => a.email.localeCompare(b.email));
}

function getFolderPaths(folders: ProjectFolder[]): Map<string, string> {
	const byId = new Map(folders.map((folder) => [folder.folderId, folder]));
	const paths = new Map<string, string>();
	for (const folder of folders) {
		const segments: string[] = [];
		const visited = new Set<string>();
		let current: ProjectFolder | undefined = folder;
		while (current && !visited.has(current.folderId)) {
			visited.add(current.folderId);
			segments.unshift(current.name);
			current = current.parentFolderId
				? byId.get(current.parentFolderId)
				: undefined;
		}
		paths.set(folder.folderId, segments.join(" / "));
	}
	return paths;
}

function projectRoleLabel(role: ProjectRole): string {
	return {
		Owner: "所有者",
		Manage: "管理者",
		Edit: "编辑",
		Comment: "评论",
		Read: "只读",
	}[role];
}

function invitationState(state: string): string {
	return (
		{
			Pending: "待接受",
			Accepted: "已接受",
			Expired: "已过期",
			Revoked: "已撤销",
		}[state] ?? state
	);
}
