/**
 * Minimal typed API client for the DOM auth surface (doc 27 §17).
 *
 * This package is the ONLY place ``fetch()`` lives on the frontend (arch
 * direction: apps/web -> client-sdk -> contracts). It speaks the generated
 * @dom/contracts types for every request/response body; the session
 * (``dom_session``) and device (``dom_device``) cookies are managed by the
 * browser per the server's Set-Cookie (HttpOnly, SameSite=Lax) and are sent
 * with ``credentials: "same-origin"`` through the web dev proxy.
 *
 * Device identity (FR-AUTH-013): the server issues ``dom_device`` once; the
 * client mirrors a stable per-origin device id in localStorage so a brand-new
 * browser profile still presents a consistent device before the server cookie
 * round-trips (and multi-tab shares it automatically through the cookie jar).
 */

import type { components, operations } from "@dom/contracts/client-api";
import type { LoginWithPassword } from "@dom/contracts/commands/auth/login-with-password";
import type { LoginWithPasswordResponse } from "@dom/contracts/commands/auth/login-with-password-response";
import type { LogoutResponse } from "@dom/contracts/commands/auth/logout";
import type { RegisterWithEmail } from "@dom/contracts/commands/auth/register-with-email";
import type { RegisterWithEmailResponse } from "@dom/contracts/commands/auth/register-with-email-response";
import type { RequestPasswordReset } from "@dom/contracts/commands/auth/request-password-reset";
import type { RequestPasswordResetResponse } from "@dom/contracts/commands/auth/request-password-reset-response";
import type { ResendEmailVerification } from "@dom/contracts/commands/auth/resend-email-verification";
import type { ResendEmailVerificationResponse } from "@dom/contracts/commands/auth/resend-email-verification-response";
import type { ResetPassword } from "@dom/contracts/commands/auth/reset-password";
import type { ResetPasswordResponse } from "@dom/contracts/commands/auth/reset-password-response";
import type { VerifyEmail } from "@dom/contracts/commands/auth/verify-email";
import type { VerifyEmailResponse } from "@dom/contracts/commands/auth/verify-email-response";
import type { AuthErrorCategory } from "@dom/contracts/errors/error-envelope";
import type { GetCurrentAccountResponse } from "@dom/contracts/queries/auth/get-current-account";
import type { GetCurrentSessionResponse } from "@dom/contracts/queries/auth/get-current-session";

type CreateWorkspaceRequest = Omit<
	components["schemas"]["create-workspace.schema"],
	"$defs"
>;
type CreateWorkspaceResponse = components["schemas"]["CreateWorkspaceResponse"];
type WorkspaceResponse = components["schemas"]["get-workspace.schema"];
type OpenResourceResponse = components["schemas"]["open-resource.schema"];
type GetResourceCapabilitiesResponse =
	components["schemas"]["get-resource-capabilities.schema"];
type CreateResourceRequest = Omit<
	components["schemas"]["create-resource.schema"],
	"$defs"
>;
type CreateResourceResponse =
	components["schemas"]["create-resource.schema"]["$defs"]["CreateResourceResponse"];
type AppendJournalOpRequest = Omit<
	components["schemas"]["append-journal-op.schema"],
	"$defs"
>;
type AppendJournalOpResponse =
	components["schemas"]["append-journal-op.schema"]["$defs"]["AppendJournalOpResponse"];
type RenameResourceRequest = Omit<
	components["schemas"]["rename-resource.schema"],
	"$defs"
>;
type RenameResourceResponse =
	components["schemas"]["rename-resource.schema"]["$defs"]["RenameResourceResponse"];
type TrashResourceRequest = Omit<
	components["schemas"]["trash-resource.schema"],
	"$defs"
>;
type TrashResourceResponse =
	components["schemas"]["trash-resource.schema"]["$defs"]["TrashResourceResponse"];
type RestoreResourceRequest = Omit<
	components["schemas"]["restore-resource.schema"],
	"$defs"
>;
type RestoreResourceResponse =
	components["schemas"]["restore-resource.schema"]["$defs"]["RestoreResourceResponse"];
type AddCommentRequest = Omit<
	components["schemas"]["add-comment.schema"],
	"$defs"
>;
type AddCommentResponse =
	components["schemas"]["add-comment.schema"]["$defs"]["AddCommentResponse"];
type ListCommentsResponse = components["schemas"]["list-comments.schema"];
export type CommentThreadStatus =
	ListCommentsResponse["items"][number]["status"];
export type ResolveCommentThreadResponse =
	components["schemas"]["resolve-comment-thread.schema"];
export type ReopenCommentThreadResponse =
	components["schemas"]["reopen-comment-thread.schema"];
type ResourceId = components["schemas"]["ResourceId"];
type ThreadId = components["schemas"]["ThreadId"];
type SearchWorkspaceResponse = components["schemas"]["search-workspace.schema"];
type ListWorkspacesResponse = components["schemas"]["list-workspaces.schema"];
type ListProjectsResponse = components["schemas"]["list-projects.schema"];
type ListResourcesResponse = components["schemas"]["list-resources.schema"];
type ListResourcesQuery = NonNullable<
	operations["ListResources"]["parameters"]["query"]
>;
type TransferOwnerRequest =
	components["schemas"]["transfer-workspace-owner.schema"];
type TransferOwnerResponse =
	components["schemas"]["TransferWorkspaceOwnerResponse"];
type CreateProjectRequest = Omit<
	components["schemas"]["create-project.schema"],
	"$defs"
>;
type CreateProjectResponse = components["schemas"]["CreateProjectResponse"];
type CreateFolderRequest = Omit<
	components["schemas"]["create-folder.schema"],
	"$defs"
>;
type CreateFolderResponse = components["schemas"]["CreateFolderResponse"];
type MoveFolderRequest = components["schemas"]["move-folder.schema"];
type MoveFolderResponse = components["schemas"]["MoveFolderResponse"];
type ProjectTreeResponse = components["schemas"]["get-project-tree.schema"];
type WorkspaceId = components["schemas"]["WorkspaceId"];
type ProjectId = components["schemas"]["ProjectId"];
type FolderId = components["schemas"]["FolderId"];
type IdempotencyKey = components["schemas"]["IdempotencyKey"];
type ListTasksQuery = NonNullable<
	operations["ListTasks"]["parameters"]["query"]
>;
type ListTasksResponse = components["schemas"]["list-tasks.schema"];
type GetTaskResponse = components["schemas"]["get-task.schema"];
type CancelTaskResponse = components["schemas"]["cancel-task.schema"];
type RetryTaskResponse = components["schemas"]["retry-task.schema"];
type CreateWorkspaceInvitationRequest = Omit<
	components["schemas"]["create-workspace-invitation.schema"],
	"$defs"
>;
type CreateWorkspaceInvitationResponse =
	components["schemas"]["CreateWorkspaceInvitationResponse"];
type AcceptWorkspaceInvitationRequest = Omit<
	components["schemas"]["accept-workspace-invitation.schema"],
	"$defs"
>;
type AcceptWorkspaceInvitationResponse =
	components["schemas"]["AcceptWorkspaceInvitationResponse"];
type ListWorkspaceMembersResponse =
	components["schemas"]["list-workspace-members.schema"];
type ListWorkspaceInvitationsResponse =
	components["schemas"]["list-workspace-invitations.schema"];
type SuggestMembersResponse =
	components["schemas"]["member-suggestions.schema"];
type RevokeWorkspaceInvitationResponse =
	components["schemas"]["RevokeWorkspaceInvitationResponse"];
type RemoveWorkspaceMemberResponse =
	components["schemas"]["RemoveWorkspaceMemberResponse"];
type ListProjectMembersResponse =
	components["schemas"]["list-project-members.schema"];
export type ProjectPermissionRole =
	components["schemas"]["set-project-member-role.schema"]["role"];
type SetProjectMemberRoleResponse =
	components["schemas"]["SetProjectMemberRoleResponse"];
type RemoveProjectMemberResponse =
	components["schemas"]["RemoveProjectMemberResponse"];
type ListResourcePermissionsResponse =
	components["schemas"]["list-resource-permissions.schema"];
type ResourcePermissionRole =
	components["schemas"]["set-resource-permission.schema"]["role"];
type SetResourcePermissionResponse =
	components["schemas"]["SetResourcePermissionResponse"];
type RemoveResourcePermissionResponse =
	components["schemas"]["RemoveResourcePermissionResponse"];
type UploadAssetResponse = components["schemas"]["UploadAssetResponse"];
type ListResourceAssetsResponse =
	components["schemas"]["list-resource-assets.schema"];
type CreateResourceShareLinkRequest = Omit<
	components["schemas"]["create-resource-share-link.schema"],
	"$defs"
>;
type CreateResourceShareLinkResponse =
	components["schemas"]["CreateResourceShareLinkResponse"];
type ListResourceShareLinksResponse =
	components["schemas"]["list-resource-share-links.schema"];
type SetResourceShareLinkExpiryRequest = Omit<
	components["schemas"]["set-resource-share-link-expiry.schema"],
	"$defs"
>;
type SetResourceShareLinkExpiryResponse =
	components["schemas"]["SetResourceShareLinkExpiryResponse"];
type RevokeResourceShareLinkResponse =
	components["schemas"]["revoke-resource-share-link.schema"];
type RegenerateResourceShareLinkRequest = Omit<
	components["schemas"]["regenerate-resource-share-link.schema"],
	"$defs"
>;
type RegenerateResourceShareLinkResponse =
	components["schemas"]["RegenerateResourceShareLinkResponse"];
export type OpenPublicSharedResourceResponse =
	components["schemas"]["open-public-shared-resource.schema"];
type ProposeChangeSetRequest = Omit<
	components["schemas"]["propose-changeset.schema"],
	"$defs"
>;
type ProposeChangeSetResponse =
	operations["ProposeChangeSet"]["responses"][200]["content"]["application/json"];
type ApplyChangeSetResponse =
	operations["ApplyChangeSet"]["responses"][200]["content"]["application/json"];
type ImportResourceRequest = Omit<
	components["schemas"]["import-resource.schema"],
	"$defs"
>;
type ImportResourceResponse =
	operations["ImportResource"]["responses"][202]["content"]["application/json"];
type CreateVersionRestoreTaskResponse =
	operations["CreateVersionRestoreTask"]["responses"][202]["content"]["application/json"];
type CreateResourceExportTaskResponse =
	operations["CreateResourceExportTask"]["responses"][202]["content"]["application/json"];
type ShareId = components["schemas"]["ShareId"];
type InvitationId = components["schemas"]["InvitationId"];
type UserId = components["schemas"]["UserId"];

export function createIdempotencyKey(): IdempotencyKey {
	const bytes = new Uint8Array(16);
	let timestamp = Date.now();
	for (let index = 5; index >= 0; index -= 1) {
		bytes[index] = timestamp % 256;
		timestamp = Math.floor(timestamp / 256);
	}
	crypto.getRandomValues(bytes.subarray(6));
	bytes[6] = (bytes[6] & 0x0f) | 0x70;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = Array.from(bytes, (byte) =>
		byte.toString(16).padStart(2, "0"),
	).join("");
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}` as IdempotencyKey;
}

/** Stable per-origin device id key (mirrored to the dom_device cookie). */
export const DEVICE_ID_STORAGE_KEY = "dom:device-id";

/**
 * Error envelope projection thrown by the client on non-success statuses
 * (doc 28 §29 — generated ErrorEnvelope shape, client-side projection).
 */
export class DomApiError extends Error {
	readonly status: number;
	readonly category: AuthErrorCategory;
	readonly errorCode: string;
	readonly messageKey: string;
	readonly requestId?: string;
	readonly retryable: boolean;

	constructor(
		status: number,
		envelope: {
			category?: AuthErrorCategory;
			errorCode?: string;
			messageKey?: string;
			message?: string;
			requestId?: string;
			retryable?: boolean;
		},
	) {
		super(envelope.message ?? `HTTP ${status}`);
		this.status = status;
		this.category = envelope.category ?? "Internal";
		this.errorCode = envelope.errorCode ?? "UNKNOWN_ERROR";
		this.messageKey = envelope.messageKey ?? this.errorCode;
		this.requestId = envelope.requestId;
		this.retryable = envelope.retryable ?? false;
	}
}

export interface DomClientOptions {
	/** API base path. Defaults to the same-origin /v1 (web dev proxy -> API). */
	baseUrl?: string;
	/** Optional device id override; default keeps localStorage mirror. */
	deviceId?: string;
}

/**
 * Read the stable per-origin device id, issuing it once into localStorage and
 * keeping a ``dom_device`` cookie mirror so a first request already carries a
 * device identity (FR-AUTH-013 multi-tab shares the jar; the server's own
 * HttpOnly dom_device takes precedence after the first Set-Cookie).
 */
export function ensureDeviceId(
	storage: Pick<Storage, "getItem" | "setItem"> = window.localStorage,
): string {
	const fromCookie = deviceIdFromCookie();
	if (fromCookie !== "") {
		storage.setItem(DEVICE_ID_STORAGE_KEY, fromCookie);
		return fromCookie;
	}
	const fromStorage = storage.getItem(DEVICE_ID_STORAGE_KEY);
	if (fromStorage !== null && fromStorage !== "") {
		setDeviceIdCookie(fromStorage);
		return fromStorage;
	}
	const fresh = crypto.randomUUID();
	storage.setItem(DEVICE_ID_STORAGE_KEY, fresh);
	setDeviceIdCookie(fresh);
	return fresh;
}

function deviceIdFromCookie(): string {
	const match = document.cookie.match(/(?:^|;\s*)dom_device=([^;]+)/);
	return match ? decodeURIComponent(match[1]) : "";
}

function setDeviceIdCookie(id: string): void {
	// Intentional device-cookie issuance (plan Task 30): the client mirrors the
	// stable per-origin device id into a cookie before the server's first
	// public Set-Cookie, so multi-tab shares one device identity (FR-AUTH-013).
	// biome-ignore lint/suspicious/noDocumentCookie: deliberate cookie mirror.
	document.cookie = `dom_device=${encodeURIComponent(id)}; path=/; sameSite=lax`;
}

export class DomClient {
	private readonly baseUrl: string;
	private readonly deviceId: string;

	constructor(options: DomClientOptions = {}) {
		this.baseUrl = options.baseUrl ?? "/v1";
		this.deviceId = options.deviceId ?? ensureDeviceId();
	}

	async register(body: RegisterWithEmail): Promise<RegisterWithEmailResponse> {
		return this.request("/auth/register", { method: "POST", body });
	}

	async login(body: LoginWithPassword): Promise<LoginWithPasswordResponse> {
		return this.request("/auth/login", { method: "POST", body });
	}

	async logout(): Promise<LogoutResponse> {
		return this.request("/auth/logout", { method: "POST" });
	}

	async me(): Promise<GetCurrentAccountResponse | null> {
		return this.requestOrNull("/auth/me", { method: "GET" });
	}

	async session(): Promise<GetCurrentSessionResponse | null> {
		return this.requestOrNull("/auth/session", { method: "GET" });
	}

	async verifyEmail(body: VerifyEmail): Promise<VerifyEmailResponse> {
		return this.request("/auth/verify-email", { method: "POST", body });
	}

	async resendVerification(
		body: ResendEmailVerification,
	): Promise<ResendEmailVerificationResponse> {
		return this.request("/auth/resend-verification", {
			method: "POST",
			body,
		});
	}

	async requestPasswordReset(
		body: RequestPasswordReset,
	): Promise<RequestPasswordResetResponse> {
		return this.request("/auth/forgot-password", { method: "POST", body });
	}

	async resetPassword(body: ResetPassword): Promise<ResetPasswordResponse> {
		return this.request("/auth/reset-password", { method: "POST", body });
	}

	async createWorkspace(
		body: CreateWorkspaceRequest,
	): Promise<CreateWorkspaceResponse> {
		return this.request("/workspaces", {
			method: "POST",
			body,
			idempotencyKey: body.idempotencyKey,
		});
	}

	async listResources(
		projectId: string,
		query?: ListResourcesQuery,
	): Promise<ListResourcesResponse> {
		const search = new URLSearchParams();
		if (query?.folderId) search.set("folderId", query.folderId);
		const queryString = search.toString();
		return this.request(
			`/projects/${encodeURIComponent(projectId)}/resources${queryString ? `?${queryString}` : ""}`,
			{
				method: "GET",
			},
		);
	}

	async getResourceCapabilities(
		resourceId: ResourceId,
	): Promise<GetResourceCapabilitiesResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/capabilities`,
			{ method: "GET" },
		);
	}

	async listProjects(workspaceId: string): Promise<ListProjectsResponse> {
		return this.request(`/workspaces/${workspaceId}/projects`, {
			method: "GET",
		});
	}

	async listWorkspaces(): Promise<ListWorkspacesResponse> {
		return this.request("/workspaces", { method: "GET" });
	}

	async listWorkspaceMembers(
		workspaceId: WorkspaceId,
	): Promise<ListWorkspaceMembersResponse> {
		return this.request(
			`/workspaces/${encodeURIComponent(workspaceId)}/members`,
			{ method: "GET" },
		);
	}

	async listWorkspaceInvitations(
		workspaceId: WorkspaceId,
	): Promise<ListWorkspaceInvitationsResponse> {
		return this.request(
			`/workspaces/${encodeURIComponent(workspaceId)}/invitations`,
			{ method: "GET" },
		);
	}

	async createWorkspaceInvitation(
		workspaceId: WorkspaceId,
		body: Omit<CreateWorkspaceInvitationRequest, "workspaceId">,
	): Promise<CreateWorkspaceInvitationResponse> {
		return this.request(
			`/workspaces/${encodeURIComponent(workspaceId)}/invitations`,
			{
				method: "POST",
				body: { ...body, workspaceId },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async acceptWorkspaceInvitation(
		body: AcceptWorkspaceInvitationRequest,
	): Promise<AcceptWorkspaceInvitationResponse> {
		return this.request("/invitations/accept", { method: "POST", body });
	}

	async revokeWorkspaceInvitation(
		workspaceId: WorkspaceId,
		invitationId: InvitationId,
	): Promise<RevokeWorkspaceInvitationResponse> {
		return this.request(
			`/workspaces/${encodeURIComponent(workspaceId)}/invitations/${encodeURIComponent(invitationId)}`,
			{
				method: "DELETE",
				body: { workspaceId, invitationId },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async removeWorkspaceMember(
		workspaceId: WorkspaceId,
		accountId: UserId,
	): Promise<RemoveWorkspaceMemberResponse> {
		return this.request(
			`/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(accountId)}`,
			{
				method: "DELETE",
				body: { workspaceId, accountId },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async listProjectMembers(
		projectId: ProjectId,
	): Promise<ListProjectMembersResponse> {
		return this.request(`/projects/${encodeURIComponent(projectId)}/members`, {
			method: "GET",
		});
	}

	async setProjectMemberRole(
		projectId: ProjectId,
		accountId: UserId,
		role: ProjectPermissionRole,
	): Promise<SetProjectMemberRoleResponse> {
		return this.request(
			`/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(accountId)}`,
			{
				method: "PUT",
				body: { projectId, accountId, role },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async removeProjectMember(
		projectId: ProjectId,
		accountId: UserId,
	): Promise<RemoveProjectMemberResponse> {
		return this.request(
			`/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(accountId)}`,
			{
				method: "DELETE",
				body: { projectId, accountId },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async listResourcePermissions(
		resourceId: ResourceId,
	): Promise<ListResourcePermissionsResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/permissions`,
			{ method: "GET" },
		);
	}

	async setResourcePermission(
		resourceId: ResourceId,
		accountId: UserId,
		role: ResourcePermissionRole,
	): Promise<SetResourcePermissionResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/permissions/${encodeURIComponent(accountId)}`,
			{
				method: "PUT",
				body: { resourceId, accountId, role },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async removeResourcePermission(
		resourceId: ResourceId,
		accountId: UserId,
	): Promise<RemoveResourcePermissionResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/permissions/${encodeURIComponent(accountId)}`,
			{
				method: "DELETE",
				body: { resourceId, accountId },
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async uploadAsset(
		resourceId: ResourceId,
		file: File,
		idempotencyKey: IdempotencyKey,
	): Promise<UploadAssetResponse> {
		const form = new FormData();
		form.append("file", file, file.name);
		if (file.type) form.append("mime", file.type);
		const response = await window.fetch(
			`${this.baseUrl}/resources/${encodeURIComponent(resourceId)}/assets`,
			{
				method: "POST",
				body: form,
				headers: { "Idempotency-Key": idempotencyKey },
				credentials: "same-origin",
			},
		);
		if (!response.ok) throw await this.toError(response);
		return (await response.json()) as UploadAssetResponse;
	}

	async listResourceAssets(
		resourceId: ResourceId,
	): Promise<ListResourceAssetsResponse> {
		return this.request(`/resources/${encodeURIComponent(resourceId)}/assets`, {
			method: "GET",
		});
	}

	assetUrl(assetId: string): string {
		return `${this.baseUrl}/assets/${encodeURIComponent(assetId)}`;
	}

	async downloadAsset(assetId: string): Promise<Blob> {
		const response = await window.fetch(
			`${this.baseUrl}/assets/${encodeURIComponent(assetId)}`,
			{ method: "GET", credentials: "same-origin" },
		);
		if (!response.ok) throw await this.toError(response);
		return response.blob();
	}

	async createResourceShareLink(
		resourceId: ResourceId,
		body: CreateResourceShareLinkRequest,
	): Promise<CreateResourceShareLinkResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/share-links`,
			{
				method: "POST",
				body,
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async listResourceShareLinks(
		resourceId: ResourceId,
	): Promise<ListResourceShareLinksResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/share-links`,
			{ method: "GET" },
		);
	}

	async setResourceShareLinkExpiry(
		resourceId: ResourceId,
		shareId: ShareId,
		body: SetResourceShareLinkExpiryRequest,
	): Promise<SetResourceShareLinkExpiryResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/share-links/${encodeURIComponent(shareId)}`,
			{
				method: "PATCH",
				body,
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async revokeResourceShareLink(
		resourceId: ResourceId,
		shareId: ShareId,
	): Promise<RevokeResourceShareLinkResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/share-links/${encodeURIComponent(shareId)}`,
			{ method: "DELETE", idempotencyKey: crypto.randomUUID() },
		);
	}

	async regenerateResourceShareLink(
		resourceId: ResourceId,
		shareId: ShareId,
		body: RegenerateResourceShareLinkRequest,
	): Promise<RegenerateResourceShareLinkResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/share-links/${encodeURIComponent(shareId)}/regenerate`,
			{
				method: "POST",
				body,
				idempotencyKey: crypto.randomUUID(),
			},
		);
	}

	async openPublicSharedResource(
		token: string,
	): Promise<OpenPublicSharedResourceResponse> {
		return this.request(`/public/shares/${encodeURIComponent(token)}`, {
			method: "GET",
		});
	}

	publicSharedAssetUrl(token: string, assetId: string): string {
		return `${this.baseUrl}/public/shares/${encodeURIComponent(token)}/assets/${encodeURIComponent(assetId)}`;
	}

	async downloadPublicSharedAsset(
		token: string,
		assetId: string,
	): Promise<Blob> {
		const response = await window.fetch(
			this.publicSharedAssetUrl(token, assetId),
			{
				method: "GET",
				credentials: "same-origin",
				cache: "no-store",
			},
		);
		if (!response.ok) throw await this.toError(response);
		return response.blob();
	}

	async createResource(
		body: CreateResourceRequest,
	): Promise<CreateResourceResponse> {
		return this.request("/resources", {
			method: "POST",
			body,
			idempotencyKey: body.idempotencyKey,
		});
	}

	async renameResource(
		resourceId: string,
		body: Omit<RenameResourceRequest, "resourceId">,
	): Promise<RenameResourceResponse> {
		return this.request(`/resources/${resourceId}`, {
			method: "PATCH",
			body: { ...body, resourceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async addComment(
		resourceId: string,
		body: Omit<AddCommentRequest, "resourceId">,
	): Promise<AddCommentResponse> {
		return this.request(`/resources/${resourceId}/comments`, {
			method: "POST",
			body: { ...body, resourceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async resolveCommentThread(
		resourceId: ResourceId,
		threadId: ThreadId,
	): Promise<ResolveCommentThreadResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/comments/threads/${encodeURIComponent(threadId)}/resolve`,
			{ method: "POST" },
		);
	}

	async reopenCommentThread(
		resourceId: ResourceId,
		threadId: ThreadId,
	): Promise<ReopenCommentThreadResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/comments/threads/${encodeURIComponent(threadId)}/reopen`,
			{ method: "POST" },
		);
	}

	async listHistory(resourceId: string): Promise<{
		resourceId: string;
		items: Array<{
			seq: number;
			kind: string;
			label: string | null;
			author: string | null;
			occurredAt: string | null;
		}>;
	}> {
		return this.request(`/resources/${resourceId}/history`, { method: "GET" });
	}

	async listNotifications(): Promise<{
		items: Array<{
			notificationId: string;
			kind: string;
			payload: unknown;
			createdAt: string | null;
			readAt: string | null;
		}>;
		unreadCount: number;
	}> {
		return this.request(`/notifications`, { method: "GET" });
	}

	async markNotificationRead(
		notificationId: string,
	): Promise<{ notificationId: string; readAt: string }> {
		return this.request(`/notifications/${notificationId}/read`, {
			method: "POST",
		});
	}

	async markAllNotificationsRead(): Promise<{ marked: number }> {
		return this.request(`/notifications/read-all`, { method: "POST" });
	}

	async createNamedVersion(
		resourceId: string,
		label: string,
		baseJournalSeq: number,
	): Promise<{
		resourceId: string;
		versionId: string;
		label: string;
		baseJournalSeq: number;
	}> {
		return this.request(`/resources/${resourceId}/versions`, {
			method: "POST",
			body: { resourceId, label, baseJournalSeq },
			idempotencyKey: crypto.randomUUID(),
		});
	}

	async restoreVersion(
		resourceId: string,
		baseJournalSeq: number,
	): Promise<{
		resourceId: string;
		newSeq: number;
		label: string;
	}> {
		return this.request(`/resources/${resourceId}/history/restore`, {
			method: "POST",
			body: { baseJournalSeq },
		});
	}

	async clearSearchHistory(): Promise<{ cleared: number }> {
		return this.request(`/search/history`, { method: "DELETE" });
	}

	async suggestMembers(
		workspaceId: string,
		query: string,
	): Promise<SuggestMembersResponse> {
		return this.request(
			`/workspaces/${workspaceId}/members/suggest?q=${encodeURIComponent(query)}`,
			{ method: "GET" },
		);
	}

	async proposeChangeSet(
		resourceId: ResourceId,
		instruction: string,
	): Promise<ProposeChangeSetResponse> {
		return this.request(`/ai/propose-changeset`, {
			method: "POST",
			body: { resourceId, instruction } satisfies ProposeChangeSetRequest,
		});
	}

	async applyChangeSet(changesetId: string): Promise<ApplyChangeSetResponse> {
		return this.request(`/changesets/${changesetId}/apply`, {
			method: "POST",
			body: {},
			idempotencyKey: crypto.randomUUID(),
		});
	}

	async createVersionRestoreTask(
		resourceId: ResourceId,
		baseJournalSeq: number,
		idempotencyKey: IdempotencyKey,
	): Promise<CreateVersionRestoreTaskResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/versions/${baseJournalSeq}/restore-tasks`,
			{ method: "POST", idempotencyKey },
		);
	}

	async importResource(
		resourceId: ResourceId,
		document: ImportResourceRequest["document"],
		idempotencyKey: IdempotencyKey,
	): Promise<ImportResourceResponse> {
		return this.request(`/resources/${encodeURIComponent(resourceId)}/import`, {
			method: "POST",
			body: {
				resourceId,
				document,
				idempotencyKey,
			} satisfies ImportResourceRequest,
			idempotencyKey,
		});
	}

	async createResourceExportTask(
		resourceId: ResourceId,
		idempotencyKey: IdempotencyKey,
	): Promise<CreateResourceExportTaskResponse> {
		return this.request(
			`/resources/${encodeURIComponent(resourceId)}/export-tasks`,
			{ method: "POST", idempotencyKey },
		);
	}

	async getResourceExportResult(
		resourceId: ResourceId,
		exportSessionId: string,
	): Promise<Blob> {
		const response = await window.fetch(
			`${this.baseUrl}/resources/${encodeURIComponent(resourceId)}/exports/${encodeURIComponent(exportSessionId)}/result`,
			{ method: "GET", credentials: "same-origin" },
		);
		if (!response.ok) throw await this.toError(response);
		return response.blob();
	}

	async searchHistory(): Promise<{
		items: Array<{ query: string; lastUsedAt: string | null }>;
	}> {
		return this.request(`/search/history`, { method: "GET" });
	}

	async searchWorkspace(
		workspaceId: string,
		query: string,
	): Promise<SearchWorkspaceResponse> {
		return this.request(
			`/workspaces/${workspaceId}/search?q=${encodeURIComponent(query)}`,
			{
				method: "GET",
			},
		);
	}

	async listComments(resourceId: string): Promise<ListCommentsResponse> {
		return this.request(`/resources/${resourceId}/comments`, {
			method: "GET",
		});
	}

	async listTasks(query?: ListTasksQuery): Promise<ListTasksResponse> {
		const search = new URLSearchParams();
		if (query?.limit !== undefined) search.set("limit", String(query.limit));
		if (query?.offset !== undefined) search.set("offset", String(query.offset));
		const queryString = search.toString();
		return this.request(`/tasks${queryString ? `?${queryString}` : ""}`, {
			method: "GET",
		});
	}

	async getTask(taskId: string): Promise<GetTaskResponse> {
		return this.request(`/tasks/${encodeURIComponent(taskId)}`, {
			method: "GET",
		});
	}

	async cancelTask(taskId: string): Promise<CancelTaskResponse> {
		return this.request(`/tasks/${encodeURIComponent(taskId)}/cancel`, {
			method: "POST",
		});
	}

	async retryTask(
		taskId: string,
		idempotencyKey: IdempotencyKey,
	): Promise<RetryTaskResponse> {
		return this.request(`/tasks/${encodeURIComponent(taskId)}/retry`, {
			method: "POST",
			idempotencyKey,
		});
	}

	async restoreResource(
		resourceId: string,
		body: Omit<RestoreResourceRequest, "resourceId">,
	): Promise<RestoreResourceResponse> {
		return this.request(`/resources/${resourceId}/restore`, {
			method: "POST",
			body: { ...body, resourceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async trashResource(
		resourceId: string,
		body: Omit<TrashResourceRequest, "resourceId">,
	): Promise<TrashResourceResponse> {
		return this.request(`/resources/${resourceId}/trash`, {
			method: "POST",
			body: { ...body, resourceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async appendJournalOp(
		resourceId: string,
		body: Omit<AppendJournalOpRequest, "resourceId">,
	): Promise<AppendJournalOpResponse> {
		return this.request(`/resources/${resourceId}/journal`, {
			method: "POST",
			body: { ...body, resourceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async openResource(resourceId: string): Promise<OpenResourceResponse> {
		return this.request(`/resources/${resourceId}`, { method: "GET" });
	}

	async getWorkspace(workspaceId: WorkspaceId): Promise<WorkspaceResponse> {
		return this.request(`/workspaces/${workspaceId}`, { method: "GET" });
	}

	async transferOwner(
		workspaceId: WorkspaceId,
		body: Omit<TransferOwnerRequest, "workspaceId">,
	): Promise<TransferOwnerResponse> {
		return this.request(`/workspaces/${workspaceId}/owner`, {
			method: "POST",
			body: { ...body, workspaceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async createProject(
		workspaceId: WorkspaceId,
		body: Omit<CreateProjectRequest, "workspaceId">,
	): Promise<CreateProjectResponse> {
		return this.request(`/workspaces/${workspaceId}/projects`, {
			method: "POST",
			body: { ...body, workspaceId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async createFolder(
		projectId: ProjectId,
		body: Omit<CreateFolderRequest, "projectId">,
	): Promise<CreateFolderResponse> {
		return this.request(`/projects/${projectId}/folders`, {
			method: "POST",
			body: { ...body, projectId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async moveFolder(
		folderId: FolderId,
		body: Omit<MoveFolderRequest, "folderId">,
	): Promise<MoveFolderResponse> {
		return this.request(`/folders/${folderId}/move`, {
			method: "POST",
			body: { ...body, folderId },
			idempotencyKey: body.idempotencyKey,
		});
	}

	async getProjectTree(projectId: ProjectId): Promise<ProjectTreeResponse> {
		return this.request(`/projects/${projectId}`, { method: "GET" });
	}

	private async request<T>(
		path: string,
		init: { method: string; body?: object; idempotencyKey?: IdempotencyKey },
	): Promise<T> {
		const response = await this.fetch(path, init);
		if (!response.ok) {
			throw await this.toError(response);
		}
		return (await response.json()) as T;
	}

	private async requestOrNull<T>(
		path: string,
		init: { method: string; body?: object; idempotencyKey?: IdempotencyKey },
	): Promise<T | null> {
		const response = await this.fetch(path, init);
		if (!response.ok) {
			if (response.status === 401) {
				// Unauthenticated is a state, not an error, for these queries.
				return null;
			}
			throw await this.toError(response);
		}
		return (await response.json()) as T;
	}

	private async fetch(
		path: string,
		init: { method: string; body?: object; idempotencyKey?: IdempotencyKey },
	): Promise<Response> {
		const headers: Record<string, string> = {
			"content-type": "application/json",
		};
		if (init.idempotencyKey !== undefined) {
			headers["Idempotency-Key"] = init.idempotencyKey;
		}
		return window.fetch(`${this.baseUrl}${path}`, {
			method: init.method,
			headers,
			body: init.body === undefined ? undefined : JSON.stringify(init.body),
			credentials: "same-origin",
		});
	}

	private async toError(response: Response): Promise<DomApiError> {
		let envelope: {
			category?: AuthErrorCategory;
			errorCode?: string;
			messageKey?: string;
			message?: string;
			requestId?: string;
			retryable?: boolean;
		} = {};
		try {
			const parsed = (await response.json()) as typeof envelope;
			if (parsed && typeof parsed === "object") {
				envelope = parsed;
			}
		} catch {
			// Non-JSON body: keep empty envelope, fall back to status copy.
		}
		return new DomApiError(response.status, envelope);
	}
}
