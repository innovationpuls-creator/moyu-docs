/**
 * /forgot-password 页（A 组 · 墨屿 · Moyu Docs 视觉基线，spec §5.4）。
 *
 * 绝对防枚举：无论邮箱是否注册，接口恒返回成功（auth_password.py uniform
 * FORGOT_PASSWORD_SUCCESS）。响应携带 nextAllowedAt（服务端权威）驱动 60s
 * 重发倒计时；RATE_LIMITED 时展示温和冷却提示（同 resend 冷却机制，60s/5次24h）。
 */

import { DomApiError, DomClient } from "@dom/client-sdk";
import {
	type AuthShell,
	bindOffline,
	cardHeader,
	createAuthShell,
	feedbackBar,
	fieldHint,
	formGroup,
	gentleShake,
	primaryButton,
	setLoading,
	startCountdown,
	textInput,
} from "../components/auth";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COOLDOWN_FALLBACK_SECONDS = 60;

export async function renderForgotPasswordPage(
	app: HTMLElement,
): Promise<void> {
	const client = new DomClient();
	app.replaceChildren();

	const shell: AuthShell = createAuthShell();
	const { card, notice } = shell;

	const form = document.createElement("form");
	form.dataset.testid = "forgot-password-form";
	form.noValidate = true;

	const feedbackSlot = document.createElement("div");

	const emailGroup = formGroup("注册邮箱", { forId: "forgotEmail" });
	const email = textInput({
		testId: "email-input",
		type: "email",
		placeholder: "designer@company.com",
		autocomplete: "email",
		required: true,
	});
	email.id = "forgotEmail";
	emailGroup.wrapper.append(email);
	const emailHint = fieldHint("error", "请输入有效的邮箱地址");
	emailGroup.group.append(emailHint);

	const submit = primaryButton("发　送　重　置　链　接", "forgot-submit");

	const footer = document.createElement("div");
	footer.className = "card-footer";
	footer.append(document.createTextNode("记起密码了？"));
	const toLogin = document.createElement("a");
	toLogin.textContent = "返回登录";
	toLogin.href = "/login";
	footer.append(toLogin);

	form.append(
		cardHeader(
			"找回密码",
			"输入您的注册邮箱，我们将向您发送 15 分钟有效的重置链接",
		),
		feedbackSlot,
		emailGroup.group,
		submit,
		footer,
	);
	card.append(form);
	app.append(shell.root);

	let busy = false;
	let offline = false;
	let cooldownUntil: number | null = null;
	let cooldownStop: (() => void) | null = null;

	const syncSubmit = (): void => {
		const cooling = cooldownUntil !== null && Date.now() < cooldownUntil;
		submit.disabled = busy || offline || cooling;
		if (cooling && cooldownUntil !== null) {
			const remaining = Math.max(
				0,
				Math.ceil((cooldownUntil - Date.now()) / 1000),
			);
			submit.replaceChildren();
			const span = document.createElement("span");
			span.textContent = `请稍候，发送太快啦（${remaining}s）`;
			submit.append(span);
		} else if (!busy) {
			setLoading(submit, false, "发　送　重　置　链　接");
		}
	};

	const startCooldown = (seconds: number): void => {
		cooldownUntil = Date.now() + seconds * 1000;
		cooldownStop = startCountdown(seconds, () => {
			if (cooldownUntil !== null && Date.now() < cooldownUntil) {
				syncSubmit();
			} else {
				cooldownUntil = null;
				syncSubmit();
			}
		});
		syncSubmit();
	};

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		if (busy) return;
		feedbackSlot.replaceChildren();
		if (email.value.trim() === "") {
			emailHint.textContent = "请填写您的邮箱";
			emailHint.hidden = false;
			email.classList.add("has-error");
			gentleShake(card);
			email.focus();
			return;
		}
		if (!EMAIL_RE.test(email.value.trim())) {
			emailHint.textContent = "请输入有效的邮箱地址";
			emailHint.hidden = false;
			email.classList.add("has-error");
			gentleShake(card);
			email.focus();
			return;
		}

		busy = true;
		setLoading(submit, true, "发　送　重　置　链　接");
		void (async () => {
			try {
				const result = await client.requestPasswordReset({
					email: email.value.trim(),
				});
				busy = false;
				// 绝对防枚举（spec §5.4 态4）：接口恒成功。
				feedbackSlot.replaceChildren(
					feedbackBar(
						"success",
						"邮件已发出！若邮箱已注册，请在 15 分钟内查收。",
					),
				);
				const nextAt = Date.parse(result.nextAllowedAt);
				const seconds = Number.isFinite(nextAt)
					? Math.max(0, Math.ceil((nextAt - Date.now()) / 1000))
					: COOLDOWN_FALLBACK_SECONDS;
				startCooldown(Math.max(1, seconds));
			} catch (cause) {
				busy = false;
				if (
					cause instanceof DomApiError &&
					cause.errorCode === "RATE_LIMITED"
				) {
					feedbackSlot.replaceChildren(
						feedbackBar("warning", "发送太快啦，请稍等片刻再试。"),
					);
					startCooldown(COOLDOWN_FALLBACK_SECONDS);
				} else {
					feedbackSlot.replaceChildren(
						feedbackBar(
							"danger",
							cause instanceof Error
								? cause.message
								: "邮件发送未能完成，请检查网络设置。",
						),
					);
				}
				syncSubmit();
			}
		})();
	});

	const unbind = bindOffline(notice, (isOffline) => {
		offline = isOffline;
		syncSubmit();
	});
	window.addEventListener("beforeunload", () => {
		unbind();
		cooldownStop?.();
	});
}
