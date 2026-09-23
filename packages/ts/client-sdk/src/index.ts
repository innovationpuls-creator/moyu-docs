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

import type { LoginWithPasswordResponse } from "@dom/contracts/commands/auth/login-with-password-response";
import type { LogoutResponse } from "@dom/contracts/commands/auth/logout";
import type { RegisterWithEmailResponse } from "@dom/contracts/commands/auth/register-with-email-response";
import type { AuthErrorCategory } from "@dom/contracts/errors/error-envelope";
import type { GetCurrentAccountResponse } from "@dom/contracts/queries/auth/get-current-account";
import type { GetCurrentSessionResponse } from "@dom/contracts/queries/auth/get-current-session";

export interface RegisterWithEmailBody {
	email: string;
	password: string;
}

export interface LoginWithPasswordBody {
	email: string;
	password: string;
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

	async register(
		body: RegisterWithEmailBody,
	): Promise<RegisterWithEmailResponse> {
		return this.request("/auth/register", { method: "POST", body });
	}

	async login(body: LoginWithPasswordBody): Promise<LoginWithPasswordResponse> {
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

	private async request<T>(
		path: string,
		init: { method: string; body?: object },
	): Promise<T> {
		const response = await this.fetch(path, init);
		if (!response.ok) {
			throw await this.toError(response);
		}
		return (await response.json()) as T;
	}

	private async requestOrNull<T>(
		path: string,
		init: { method: string; body?: object },
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
		init: { method: string; body?: object },
	): Promise<Response> {
		return window.fetch(`${this.baseUrl}${path}`, {
			method: init.method,
			headers: {
				"content-type": "application/json",
			},
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
