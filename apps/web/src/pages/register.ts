/**
 * /register page: email + password -> DomClient.register. A NEW account gets a
 * session cookie from the server (registration auto-session); the page then
 * navigates to /workspace. An existing session skips the form.
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

export function renderRegisterPage(app: HTMLElement): void {
	const client = new DomClient();
	void (async () => {
		if ((await client.me()) !== null) {
			navigate("/workspace");
			return;
		}
		app.replaceChildren();

		const heading = document.createElement("h1");
		heading.textContent = "注册";

		const form = document.createElement("form");
		form.dataset.testid = "register-form";
		const email = emailInput();
		const password = passwordInput();
		const error = errorText();
		const submit = submitButton("注册", "register-submit");
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
					await client.register({
						email: email.value,
						password: password.value,
					});
					navigate("/workspace");
				} catch (cause) {
					error.textContent =
						cause instanceof Error ? cause.message : "注册失败，请重试";
					error.hidden = false;
				}
			})();
		});

		app.append(heading, form);
	})();
}
