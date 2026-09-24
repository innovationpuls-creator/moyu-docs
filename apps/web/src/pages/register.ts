/**
 * /register 页（A 组 · 墨屿 · Moyu Docs 视觉基线）。
 *
 * 后端行为（auth_registration.py，USER RULING）：注册对新旧邮箱恒返回 201，
 * 但仅对全新账号颁发会话 Cookie、且不向已存在邮箱发送任何邮件。因此注册请求
 * 成功后前端调 me() 分流（spec §5.2 态4）：
 *   - me() !== null → 新账号，进入 /workspace（自动登录）；
 *   - me() === null → 邮箱已存在，提示"该邮箱可能已注册，请直接登录"。
 * E2E 契约：data-testid email-input / password-input，成功后落 /workspace。
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
	secondaryButton,
	setLoading,
	startCountdown,
	textInput,
} from "../components/auth";
import { navigate } from "../main";

const MIN_PASSWORD_LENGTH = 12; // PASSWORD_TOO_WEAK（长度 12-128）
const REGISTER_COOLDOWN_SECONDS = 60; // 客户端兜底冷却（429 无服务端剩余时间）
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function renderRegisterPage(app: HTMLElement): Promise<void> {
	const client = new DomClient();
	// 并行探测会话并立即挂载页面，避免路由刷新期间等待网络请求造成空白闪现。
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
	form.dataset.testid = "register-form";
	form.noValidate = true;

	const feedbackSlot = document.createElement("div");

	const emailGroup = formGroup("工作邮箱", { forId: "registerEmail" });
	const email = textInput({
		testId: "email-input",
		type: "email",
		placeholder: "new.designer@team.org",
		autocomplete: "email",
		required: true,
	});
	email.id = "registerEmail";
	emailGroup.wrapper.append(email);
	const emailHint = fieldHint("error", "请输入有效的邮箱地址");
	emailGroup.group.append(emailHint);

	const passwordGroup = formGroup("设置密码", { forId: "registerPwd" });
	const password = textInput({
		testId: "password-input",
		type: "password",
		placeholder: "至少 12 个字符",
		autocomplete: "new-password",
		required: true,
	});
	password.id = "registerPwd";
	passwordGroup.wrapper.append(password, passwordToggle(password));
	const strengthHint = fieldHint("success", "");
	passwordGroup.group.append(strengthHint);

	const submit = primaryButton("注　册　并　进　入", "register-submit");

	const footer = document.createElement("div");
	footer.className = "card-footer";
	footer.append(document.createTextNode("已有账号？"));
	const toLogin = document.createElement("a");
	toLogin.textContent = "直接登录";
	toLogin.href = "/login";
	footer.append(toLogin);

	const actionSlot = document.createElement("div");

	form.append(
		cardHeader(
			"创建新账户",
			"用温和与自由的方式组织思想，开启本地优先协同空间",
		),
		feedbackSlot,
		emailGroup.group,
		passwordGroup.group,
		submit,
		actionSlot,
		footer,
	);
	card.append(form);
	app.append(shell.root);

	let busy = false;
	let offline = false;
	let cooldownUntil: number | null = null;
	let cooldownStop: (() => void) | null = null;

	const setFeedback = (
		kind: "danger" | "warning" | "success",
		text: string,
	): void => {
		feedbackSlot.replaceChildren(feedbackBar(kind, text));
	};

	const reflectStrength = (): void => {
		const len = password.value.length;
		if (len === 0) {
			strengthHint.hidden = true;
			strengthHint.classList.remove("error");
			return;
		}
		strengthHint.hidden = false;
		if (len < MIN_PASSWORD_LENGTH) {
			strengthHint.classList.add("error");
			strengthHint.textContent = "为了您的空间安全，密码请至少输入 12 个字符。";
		} else {
			strengthHint.classList.remove("error");
			strengthHint.textContent = `✓ 密码强度达标（已满足 ${len} 字符）`;
		}
	};
	password.addEventListener("input", reflectStrength);
	email.addEventListener("input", () => email.classList.remove("has-error"));

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
			span.textContent = `请求稍显频繁，请稍候再试（${remaining}s）`;
			submit.append(span);
		} else if (!busy) {
			setLoading(submit, false, "注　册　并　进　入");
		}
	};

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		if (busy) return;
		feedbackSlot.replaceChildren();
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
		if (password.value.length < MIN_PASSWORD_LENGTH) {
			strengthHint.classList.add("error");
			strengthHint.hidden = false;
			strengthHint.textContent = "为了您的空间安全，密码请至少输入 12 个字符。";
			if (focusTarget === null) focusTarget = password;
		}
		if (focusTarget !== null) {
			gentleShake(card);
			focusTarget.focus();
			return;
		}

		busy = true;
		setLoading(submit, true, "注　册　并　进　入");
		void (async () => {
			try {
				await client.register({
					email: email.value.trim(),
					password: password.value,
				});
				// 防枚举分流（spec §5.2 态4）：有会话 = 新账号；无会话 = 邮箱已存在。
				const session = await client.me();
				if (session !== null) {
					navigate("/workspace");
					return;
				}
				busy = false;
				setLoading(submit, false, "注　册　并　进　入");
				setFeedback("success", "该邮箱可能已注册，请直接登录。");
				actionSlot.replaceChildren(
					secondaryButton(
						"前往登录",
						() => navigate("/login"),
						"register-go-login",
					),
				);
			} catch (cause) {
				busy = false;
				if (cause instanceof DomApiError) {
					switch (cause.errorCode) {
						case "EMAIL_INVALID":
							emailHint.textContent = "请输入有效的邮箱地址。";
							emailHint.hidden = false;
							email.classList.add("has-error");
							break;
						case "PASSWORD_TOO_WEAK":
							strengthHint.classList.add("error");
							strengthHint.hidden = false;
							strengthHint.textContent =
								"为了您的空间安全，密码请至少输入 12 个字符。";
							break;
						case "RATE_LIMITED":
							cooldownUntil = Date.now() + REGISTER_COOLDOWN_SECONDS * 1000;
							cooldownStop = startCountdown(REGISTER_COOLDOWN_SECONDS, () => {
								if (cooldownUntil !== null && Date.now() < cooldownUntil) {
									syncSubmit();
								} else {
									cooldownUntil = null;
									syncSubmit();
								}
							});
							setFeedback("warning", "注册请求过于频繁，请稍候再试。");
							break;
						default:
							setFeedback("danger", cause.message || "注册失败，请稍后再试。");
					}
				} else {
					setFeedback("danger", "注册失败，请稍后再试。");
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
