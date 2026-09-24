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

import type { components } from "@dom/contracts/client-api";
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

type CreateWorkspaceRequest = components["schemas"]["create-workspace.schema"];
type CreateWorkspaceResponse = components["schemas"]["CreateWorkspaceResponse"];
type WorkspaceResponse = components["schemas"]["get-workspace.schema"];
type OpenResourceResponse = components["schemas"]["open-resource.schema"];
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
type SearchWorkspaceResponse = components["schemas"]["search-workspace.schema"];
type ListWorkspacesResponse = components["schemas"]["list-workspaces.schema"];
type ListProjectsResponse = components["schemas"]["list-projects.schema"];
type ListResourcesResponse = components["schemas"]["list-resources.schema"];
type TransferOwnerRequest =
	components["schemas"]["transfer-workspace-owner.schema"];
type TransferOwnerResponse =
	components["schemas"]["TransferWorkspaceOwnerResponse"];
type CreateProjectRequest = components["schemas"]["create-project.schema"];
type CreateProjectResponse = components["schemas"]["CreateProjectResponse"];
type CreateFolderRequest = components["schemas"]["create-folder.schema"];
type CreateFolderResponse = components["schemas"]["CreateFolderResponse"];
type MoveFolderRequest = components["schemas"]["move-folder.schema"];
type MoveFolderResponse = components["schemas"]["MoveFolderResponse"];
type ProjectTreeResponse = components["schemas"]["get-project-tree.schema"];
type WorkspaceId = components["schemas"]["WorkspaceId"];
type ProjectId = components["schemas"]["ProjectId"];
type FolderId = components["schemas"]["FolderId"];
type IdempotencyKey = components["schemas"]["IdempotencyKey"];

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

	async listResources(projectId: string): Promise<ListResourcesResponse> {
		return this.request(`/projects/${projectId}/resources`, {
			method: "GET",
		});
	}

	async listProjects(workspaceId: string): Promise<ListProjectsResponse> {
		return this.request(`/workspaces/${workspaceId}/projects`, {
			method: "GET",
		});
	}

	async listWorkspaces(): Promise<ListWorkspacesResponse> {
		return this.request("/workspaces", { method: "GET" });
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
	): Promise<{ suggestions: Array<{ accountId: string; email: string }> }> {
		return this.request(
			`/workspaces/${workspaceId}/members/suggest?q=${encodeURIComponent(query)}`,
			{ method: "GET" },
		);
	}

	async proposeChangeSet(
		resourceId: string,
		instruction: string,
	): Promise<{ changesetId: string; status: string }> {
		return this.request(`/ai/propose-changeset`, {
			method: "POST",
			body: { resourceId, instruction },
		});
	}

	async applyChangeSet(changesetId: string): Promise<{ status: string }> {
		return this.request(`/changesets/${changesetId}/apply`, {
			method: "POST",
			body: {},
			idempotencyKey: crypto.randomUUID(),
		});
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
