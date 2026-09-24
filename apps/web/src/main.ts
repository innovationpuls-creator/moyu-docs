/**
 * Web app entry: pathname router for the unauthenticated A group
 * (墨屿 · Moyu Docs visual baseline, ADR-0051) plus the authenticated surface.
 *
 * Pages:
 * - /login            email + password -> session cookie -> /workspace（已有会话直接恢复）
 * - /register         email + password -> auto session -> /workspace（重复邮箱经 me() 分流）
 * - /verify-email     验证引导页；?token= 深链消费一次性验证凭据
 * - /forgot-password  找回密码申请（绝对防枚举）
 * - /reset-password   重置密码；?token= 深链（15 分钟单次）
 * - /workspace        post-auth entry: shows the account email + logout
 * - /editor           placeholder editor: localStorage draft + realtime
 *                     SessionReplaced dialog + draft-recovery/export banner
 *
 * 未匹配路径与未登录访问统一导向 /login（A 组为唯一入口）。
 */

import "./styles/auth.css";
import { renderEditorPage } from "./pages/editor";
import { renderForgotPasswordPage } from "./pages/forgot-password";
import { renderLoginPage } from "./pages/login";
import { renderRegisterPage } from "./pages/register";
import { renderResetPasswordPage } from "./pages/reset-password";
import { renderVerifyEmailPage } from "./pages/verify-email";
import { renderWorkspacePage } from "./pages/workspace";

export function navigate(path: string): void {
	window.location.assign(path);
}

/** A 组页面的作用域（auth.css 的 body 布局/背景仅在其上生效）。 */
const AUTH_SURFACE_PATHS = new Set([
	"/login",
	"/register",
	"/verify-email",
	"/forgot-password",
	"/reset-password",
]);

function mount(): void {
	const app = document.querySelector<HTMLDivElement>("#app");
	if (!app) {
		throw new Error("#app root missing");
	}
	if (AUTH_SURFACE_PATHS.has(window.location.pathname)) {
		document.body.classList.add("auth-surface");
	} else {
		document.body.classList.remove("auth-surface");
	}
	switch (window.location.pathname) {
		case "/login":
			void renderLoginPage(app);
			break;
		case "/register":
			void renderRegisterPage(app);
			break;
		case "/verify-email":
			void renderVerifyEmailPage(app);
			break;
		case "/forgot-password":
			void renderForgotPasswordPage(app);
			break;
		case "/reset-password":
			void renderResetPasswordPage(app);
			break;
		case "/workspace":
			void renderWorkspacePage(app);
			break;
		case "/editor":
			void renderEditorPage(app);
			break;
		default:
			navigate("/login");
	}
}

mount();
