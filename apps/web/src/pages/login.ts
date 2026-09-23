/**
 * /login page: email + password -> DomClient.login. On successful login the
 * server sets the HttpOnly session cookie; the page then navigates to
 * /workspace. A valid existing session (e.g. from a previous refresh) skips
 * the form entirely and goes straight to /workspace (FR-AUTH-021).
 */

import { DomClient } from "@dom/client-sdk";
import {
	emailInput,
	errorText,
	fieldRow,
	passwordInput,
	submitButton,
} from "../lib/forms";
import { navigate } from "../main";

export function renderLoginPage(app: HTMLElement): void {
	const client = new DomClient();
	void (async () => {
		// Refresh/restart recovery: an already-valid session resumes directly.
		if ((await client.me()) !== null) {
			navigate("/workspace");
			return;
		}
		app.replaceChildren();

		const heading = document.createElement("h1");
		heading.textContent = "登录";

		const form = document.createElement("form");
		form.dataset.testid = "login-form";
		const email = emailInput();
		const password = passwordInput();
		const error = errorText();
		const submit = submitButton("登录", "login-submit");
		form.append(
			fieldRow("邮箱", email),
			fieldRow("密码", password),
			error,
			submit,
		);

		form.addEventListener("submit", (event) => {
			event.preventDefault();
			void (async () => {
				error.hidden = true;
				try {
					await client.login({ email: email.value, password: password.value });
					navigate("/workspace");
				} catch (cause) {
					error.textContent =
						cause instanceof Error ? cause.message : "登录失败，请重试";
					error.hidden = false;
				}
			})();
		});

		app.append(heading, form);
	})();
}
