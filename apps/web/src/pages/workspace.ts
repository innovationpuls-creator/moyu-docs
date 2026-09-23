/**
 * /workspace page: post-auth entry. Reads the current account via
 * DomClient.me(); if the session is no longer valid the page redirects to
 * /login (refresh/restart recovery — FR-AUTH-021). Shows the account email and
 * a logout button (FR-AUTH-020).
 */

import { DomClient } from "@dom/client-sdk";

import { navigate } from "../main";

export async function renderWorkspacePage(app: HTMLElement): Promise<void> {
	const client = new DomClient();
	const account = await client.me();
	if (account === null) {
		navigate("/login");
		return;
	}
	app.replaceChildren();

	const heading = document.createElement("h1");
	heading.textContent = "工作台";

	const email = document.createElement("p");
	email.dataset.testid = "workspace-email";
	email.textContent = account.primaryEmail;

	const editorLink = document.createElement("a");
	editorLink.href = "/editor";
	editorLink.textContent = "进入编辑器";
	editorLink.dataset.testid = "editor-link";

	const logout = document.createElement("button");
	logout.type = "button";
	logout.textContent = "退出登录";
	logout.dataset.testid = "logout-button";
	logout.addEventListener("click", () => {
		void (async () => {
			await client.logout();
			navigate("/login");
		})();
	});

	app.append(heading, email, editorLink, logout);
}
