/**
 * /login 页（A 组 · 墨屿 · Moyu Docs 视觉基线）。
 *
 * E2E 契约（browser_session_semantics.spec.ts）：data-testid
 * login-form / email-input / password-input / login-submit；密码框回车即提交；
 * 登录成功后跳 /workspace。已有会话访问时经 me() 直接恢复（FR-AUTH-021）。
 * 错误映射按 spec §5.1 / §7：INVALID_CREDENTIALS 统一防枚举文案、账号禁用单独提示、
 * RATE_LIMITED = 连续 5 次错误后的 15 分钟临时锁定（LOGIN_LOCKOUT_SECONDS=900）。
 */

import { DomApiError, DomClient } from "@dom/client-sdk";
import {
	type AuthShell,
	bindOffline,
	bindPatchworkParallax,
	cardHeader,
	createAuthShell,
	feedbackBar,
	fieldHint,
	formatLockout,
	formGroup,
	gentleShake,
	passwordToggle,
	playAuthExit,
	primaryButton,
	setLoading,
	setSuccessButton,
	startCountdown,
	textInput,
} from "../components/auth";
import { navigate } from "../main";

const LOCKOUT_SECONDS = 15 * 60; // LOGIN_LOCKOUT_SECONDS = 900（FR-AUTH-035）
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function renderLoginPage(app: HTMLElement): Promise<void> {
	const client = new DomClient();
	// 并行探测会话：有会话直接导向工作台（FR-AUTH-021）；
	// 界面在未决期间即刻挂载落位，避免网络 RTT 造成白屏停顿或动画延迟（spec §4）。
	const sessionCheck = client.me().catch(() => null);

	app.replaceChildren();

	const shell: AuthShell = createAuthShell();
	const { card, notice } = shell;

	void sessionCheck.then((user) => {
		if (user !== null) {
			navigate("/workspace");
		}
	});

	const form = document.createElement("form");
	form.dataset.testid = "login-form";
	form.noValidate = true;

	const feedbackSlot = document.createElement("div");

	// 工作邮箱
	const emailGroup = formGroup("工作邮箱", { forId: "loginEmail" });
	const email = textInput({
		testId: "email-input",
		type: "email",
		placeholder: "alex.smith@company.com",
		autocomplete: "email",
		required: true,
	});
	email.id = "loginEmail";
	emailGroup.wrapper.append(email);
	const emailHint = fieldHint("error", "请输入有效的邮箱地址");
	emailGroup.group.append(emailHint);

	// 登录密码（行内"忘记密码？"链接）
	const passwordGroup = formGroup("登录密码", {
		forId: "loginPwd",
		link: { text: "忘记密码？", href: "/forgot-password" },
	});
	const password = textInput({
		testId: "password-input",
		type: "password",
		placeholder: "••••••••••••",
		autocomplete: "current-password",
		required: true,
	});
	password.id = "loginPwd";
	passwordGroup.wrapper.append(password, passwordToggle(password));
	const passwordHint = fieldHint("error", "请输入登录密码");
	passwordGroup.group.append(passwordHint);

	const submit = primaryButton("登　入　空　间", "login-submit");

	const footer = document.createElement("div");
	footer.className = "card-footer";
	footer.append(document.createTextNode("还没有账户？"));
	const toRegister = document.createElement("a");
	toRegister.textContent = "免费创建新空间";
	toRegister.href = "/register";
	footer.append(toRegister);

	form.append(
		cardHeader("登录账户", "请输入您的工作邮箱与密码以恢复您的工作会话"),
		feedbackSlot,
		emailGroup.group,
		passwordGroup.group,
		submit,
		footer,
	);
	card.append(form);
	app.append(shell.root);
	const unbindParallax = bindPatchworkParallax(shell.root);

	let busy = false;
	let offline = false;
	let lockoutUntil: number | null = null;
	let cooldownStop: (() => void) | null = null;

	const setError = (
		kind: "danger" | "warning" | "success",
		text: string,
	): void => {
		feedbackSlot.replaceChildren(feedbackBar(kind, text));
	};

	const syncSubmit = (): void => {
		const locked = lockoutUntil !== null && Date.now() < lockoutUntil;
		submit.disabled = busy || offline || locked;
		password.disabled = locked || busy;
		if (locked && lockoutUntil !== null) {
			const remaining = Math.max(
				0,
				Math.ceil((lockoutUntil - Date.now()) / 1000),
			);
			submit.replaceChildren();
			const span = document.createElement("span");
			span.textContent = `账号临时锁定 (${formatLockout(remaining)})`;
			submit.append(span);
		} else if (!busy) {
			setLoading(submit, false, "登　入　空　间");
		}
	};

	const clearHints = (): void => {
		emailHint.hidden = true;
		passwordHint.hidden = true;
		email.classList.remove("has-error");
		password.classList.remove("has-error");
	};

	const startLockout = (): void => {
		lockoutUntil = Date.now() + LOCKOUT_SECONDS * 1000;
		cooldownStop = startCountdown(LOCKOUT_SECONDS, () => {
			if (lockoutUntil !== null && Date.now() < lockoutUntil) {
				syncSubmit();
			} else {
				lockoutUntil = null;
				syncSubmit();
			}
		});
		setError(
			"warning",
			"连续输入错误次数较多，为保障安全账号已临时锁定，请在倒计时结束后重试。",
		);
		syncSubmit();
	};

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		if (busy) return;
		clearHints();
		let focusTarget: HTMLInputElement | null = null;
		if (email.value.trim() === "") {
			emailHint.textContent = "请填写您的邮箱";
			emailHint.hidden = false;
			email.classList.add("has-error");
			focusTarget = email;
		} else if (!EMAIL_RE.test(email.value.trim())) {
			emailHint.textContent = "请输入有效的邮箱地址";
			emailHint.hidden = false;
			email.classList.add("has-error");
			focusTarget = email;
		}
		if (password.value === "") {
			passwordHint.hidden = false;
			password.classList.add("has-error");
			if (focusTarget === null) focusTarget = password;
		}
		if (focusTarget !== null) {
			gentleShake(card);
			focusTarget.focus();
			return;
		}

		busy = true;
		setLoading(submit, true, "登　入　空　间");
		void (async () => {
			try {
				await client.login({
					email: email.value.trim(),
					password: password.value,
				});
				setSuccessButton(submit, "登入成功，正在进入…");
				await playAuthExit(shell.root);
				navigate("/workspace");
			} catch (cause) {
				busy = false;
				if (cause instanceof DomApiError) {
					switch (cause.errorCode) {
						case "INVALID_CREDENTIALS":
							setError("danger", "邮箱或密码不正确，请慢慢检查后再试一次。");
							password.value = "";
							password.focus();
							break;
						case "ACCOUNT_DISABLED":
							setError(
								"danger",
								"该账号已被停用，请联系您的工作区管理员协助处理。",
							);
							break;
						case "RATE_LIMITED":
							startLockout();
							break;
						default:
							setError("danger", cause.message || "登录失败，请稍后再试。");
					}
				} else {
					setError("danger", "登录失败，请稍后再试。");
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
		unbindParallax();
		cooldownStop?.();
	});
}
