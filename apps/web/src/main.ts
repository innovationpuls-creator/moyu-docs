/**
 * Web app entry: minimal pathname router for the Phase 9 browser E2E surface
 * (UI/UX neutral — functional forms/buttons only, default styling).
 *
 * Pages:
 * - /login     email + password -> session cookie -> /workspace
 * - /register  email + password -> auto session -> /workspace
 * - /workspace post-auth entry: shows the account email + logout
 * - /editor    placeholder editor: localStorage draft + realtime
 *              SessionReplaced dialog + draft-recovery/export banner
 */

import { renderEditorPage } from "./pages/editor";
import { renderLoginPage } from "./pages/login";
import { renderRegisterPage } from "./pages/register";
import { renderWorkspacePage } from "./pages/workspace";

export function navigate(path: string): void {
	window.location.assign(path);
}

function mount(): void {
	const app = document.querySelector<HTMLDivElement>("#app");
	if (!app) {
		throw new Error("#app root missing");
	}
	switch (window.location.pathname) {
		case "/login":
			renderLoginPage(app);
			break;
		case "/register":
			renderRegisterPage(app);
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
