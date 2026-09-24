/**
 * /reset-password 页（A 组 · 墨屿 · Moyu Docs 视觉基线，spec §5.5）。
 *
 * 深链 ?token=（15 分钟单次）。缺少 token 或 PASSWORD_RESET_TOKEN_INVALID
 * → 失效引导（重新申请）；成功态不自动签发会话（FR-AUTH-027），2 秒后回跳
 * /login 重新认证。
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
	passwordToggle,
	primaryButton,
	setLoading,
	startCountdown,
	textInput,
} from "../components/auth";
import { navigate } from "../main";

const MIN_PASSWORD_LENGTH = 12;
const COOLDOWN_FALLBACK_SECONDS = 60;
const REDIRECT_DELAY_MS = 2000;

export async function renderResetPasswordPage(app: HTMLElement): Promise<void> {
	const client = new DomClient();
	const token = new URLSearchParams(window.location.search).get("token");

	app.replaceChildren();
	const shell: AuthShell = createAuthShell();
	const { card, notice } = shell;

	const body = document.createElement("div");
	card.append(body);
	app.append(shell.root);

	// Token 缺失 / 失效触发的统一引导（spec §5.5 态4）。
	if (token === null || token === "") {
		const wrap = document.createElement("div");
		const expired = feedbackBar(
			"danger",
			"重置链接已失效（时效 15 分钟且限单次使用）。",
		);
		const relink = primaryButton("重新申请密码重置", "reset-request-again");
		relink.type = "button";
		relink.addEventListener("click", () => navigate("/forgot-password"));
		const footer = document.createElement("div");
		footer.className = "card-footer";
		footer.append(document.createTextNode("想起来了？"));
		const toLogin = document.createElement("a");
		toLogin.textContent = "返回登录";
		toLogin.href = "/login";
		footer.append(toLogin);
		wrap.append(
			cardHeader("设置新密码", "请为账号输入全新的安全登录密码"),
			expired,
			relink,
			footer,
		);
		body.append(wrap);
		return;
	}

	const form = document.createElement("form");
	form.dataset.testid = "reset-password-form";
	form.noValidate = true;

	const feedbackSlot = document.createElement("div");

	const newPwdGroup = formGroup("全新密码", { forId: "newPwd1" });
	const newPassword = textInput({
		testId: "new-password-input",
		type: "password",
		placeholder: "至少 12 个字符",
		autocomplete: "new-password",
		required: true,
	});
	newPassword.id = "newPwd1";
	newPwdGroup.wrapper.append(newPassword, passwordToggle(newPassword));
	const strengthHint = fieldHint(
		"error",
		"为了您的空间安全，密码请至少输入 12 个字符。",
	);
	newPwdGroup.group.append(strengthHint);

	const confirmGroup = formGroup("确认全新密码", { forId: "newPwd2" });
	const confirmPassword = textInput({
		testId: "confirm-password-input",
		type: "password",
		placeholder: "请再次输入新密码",
		autocomplete: "new-password",
		required: true,
	});
	confirmPassword.id = "newPwd2";
	confirmGroup.wrapper.append(confirmPassword, passwordToggle(confirmPassword));
	const matchHint = fieldHint("error", "两次输入的密码不一致");
	confirmGroup.group.append(matchHint);

	const submit = primaryButton("确　认　重　置　密　码", "reset-submit");

	form.append(
		cardHeader("设置新密码", "请为账号输入全新的安全登录密码"),
		feedbackSlot,
		newPwdGroup.group,
		confirmGroup.group,
		submit,
	);
	body.append(form);

	let busy = false;
	let offline = false;
	let cooldownUntil: number | null = null;
	let cooldownStop: (() => void) | null = null;

	const reflectMatch = (): void => {
		matchHint.hidden =
			confirmPassword.value === "" ||
			confirmPassword.value === newPassword.value;
		if (newPassword.value.length >= MIN_PASSWORD_LENGTH) {
			strengthHint.hidden = true;
		}
	};
	newPassword.addEventListener("input", () => {
		if (newPassword.value.length < MIN_PASSWORD_LENGTH) {
			strengthHint.hidden = false;
		} else {
			strengthHint.hidden = true;
		}
		reflectMatch();
	});
	confirmPassword.addEventListener("input", reflectMatch);

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
			span.textContent = `请稍候，操作过快（${remaining}s）`;
			submit.append(span);
		} else if (!busy) {
			setLoading(submit, false, "确　认　重　置　密　码");
		}
	};

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		if (busy) return;
		feedbackSlot.replaceChildren();
		let focusTarget: HTMLInputElement | null = null;
		if (newPassword.value.length < MIN_PASSWORD_LENGTH) {
			strengthHint.hidden = false;
			focusTarget = newPassword;
		}
		if (confirmPassword.value !== newPassword.value) {
			matchHint.hidden = false;
			if (focusTarget === null) focusTarget = confirmPassword;
		}
		if (focusTarget !== null) {
			gentleShake(card);
			focusTarget.focus();
			return;
		}

		busy = true;
		setLoading(submit, true, "确　认　重　置　密　码");
		void (async () => {
			try {
				await client.resetPassword({
					token,
					newPassword: newPassword.value,
				});
				busy = false;
				feedbackSlot.replaceChildren(
					feedbackBar("success", "密码已重置！请使用新密码重新登录。"),
				);
				submit.replaceChildren();
				const span = document.createElement("span");
				span.textContent = "即将返回登录页…";
				submit.append(span);
				submit.disabled = true;
				window.setTimeout(() => navigate("/login"), REDIRECT_DELAY_MS);
			} catch (cause) {
				busy = false;
				if (cause instanceof DomApiError) {
					switch (cause.errorCode) {
						case "PASSWORD_RESET_TOKEN_INVALID": {
							feedbackSlot.replaceChildren(
								feedbackBar(
									"danger",
									"重置链接已失效（时效 15 分钟且限单次使用）。",
								),
							);
							submit.replaceChildren();
							const span = document.createElement("span");
							span.textContent = "重新申请密码重置";
							submit.append(span);
							submit.disabled = false;
							submit.addEventListener(
								"click",
								() => navigate("/forgot-password"),
								{ once: true },
							);
							break;
						}
						case "RATE_LIMITED":
							feedbackSlot.replaceChildren(
								feedbackBar("warning", "提交太快啦，请稍等片刻再试。"),
							);
							cooldownUntil = Date.now() + COOLDOWN_FALLBACK_SECONDS * 1000;
							cooldownStop = startCountdown(COOLDOWN_FALLBACK_SECONDS, () => {
								if (cooldownUntil !== null && Date.now() < cooldownUntil) {
									syncSubmit();
								} else {
									cooldownUntil = null;
									syncSubmit();
								}
							});
							break;
						default:
							feedbackSlot.replaceChildren(
								feedbackBar(
									"danger",
									cause.message || "重置失败，请稍后再试。",
								),
							);
					}
				} else {
					feedbackSlot.replaceChildren(
						feedbackBar("danger", "重置失败，请稍后再试。"),
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
