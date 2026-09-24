/**
 * /verify-email 页（A 组 · 墨屿 · Moyu Docs 视觉基线，spec §5.3）。
 *
 * 两种入口：
 *   1. 携带 ?token= 深链（邮件内的验证链接）：消费一次性 token（24h 单次）；
 *      EMAIL_VERIFICATION_TOKEN_INVALID → 失效引导。
 *   2. 无 token（验证引导页）：展示已验证/待验证邮箱 + 60s 重发倒计时
 *      （nextAllowedAt 服务端权威）+ "先进入工作台（受限模式）"（PendingVerification）。
 */

import { DomApiError, DomClient } from "@dom/client-sdk";
import {
	AUTH_ICONS,
	type AuthShell,
	cardHeader,
	createAuthShell,
	feedbackBar,
	primaryButton,
	secondaryButton,
	setLoading,
	startCountdown,
} from "../components/auth";
import { navigate } from "../main";

export async function renderVerifyEmailPage(app: HTMLElement): Promise<void> {
	const client = new DomClient();
	const token = new URLSearchParams(window.location.search).get("token");
	let session: Awaited<ReturnType<DomClient["me"]>> | null = null;
	try {
		session = await client.me();
	} catch {
		session = null;
	}

	app.replaceChildren();
	const shell: AuthShell = createAuthShell();
	const { card } = shell;

	const body = document.createElement("div");
	card.append(body);
	app.append(shell.root);

	const header = (title: string, description: string): HTMLElement =>
		cardHeader(title, description, { centered: true });

	const renderSingle = (node: HTMLElement): void => {
		body.replaceChildren(node);
	};

	const primaryAction = (
		label: string,
		testId: string,
		onClick: () => void,
	) => {
		const button = primaryButton(label, testId);
		button.type = "button";
		button.addEventListener("click", onClick);
		return button;
	};

	// 空态：无会话且无 token（spec §5.3 态3）。
	if (session === null && token === null) {
		const wrap = document.createElement("div");
		wrap.style.textAlign = "center";
		const icon = document.createElement("div");
		icon.style.marginBottom = "14px";
		icon.innerHTML = AUTH_ICONS.envelope;
		wrap.append(
			icon,
			header(
				"验证您的邮箱",
				"未找到待验证的账号，请先登录或使用邮件中的验证链接。",
			),
			primaryAction("前往登录页", "verify-go-login", () => navigate("/login")),
		);
		renderSingle(wrap);
		return;
	}

	const email = session?.primaryEmail ?? "";

	// 携带 token：消费验证（spec §5.3 态4 起）。
	if (token !== null) {
		const wrap = document.createElement("div");
		wrap.style.textAlign = "center";
		const icon = document.createElement("div");
		icon.style.marginBottom = "14px";
		wrap.append(icon);
		renderSingle(wrap);

		const busy = primaryButton("正在确认验证凭证…", "verify-checking");
		busy.type = "button";
		busy.disabled = true;
		wrap.append(
			icon,
			header("验证您的邮箱", "正在确认您的验证凭证，请稍候…"),
			busy,
		);
		try {
			await client.verifyEmail({ token });
			const ok = primaryAction(
				session === null ? "前往登录" : "进入工作台",
				"verify-success",
				() => navigate(session === null ? "/login" : "/workspace"),
			);
			icon.innerHTML = AUTH_ICONS.envelope;
			wrap.replaceChildren(
				icon,
				header(
					"邮箱验证成功",
					session === null
						? "您的邮箱已通过验证，请登录后解锁完整的工作区功能。"
						: "您的邮箱已通过验证，可以解锁完整的工作区功能了。",
				),
				ok,
			);
		} catch (cause) {
			if (cause instanceof DomApiError) {
				const invalid = cause.errorCode === "EMAIL_VERIFICATION_TOKEN_INVALID";
				const relink = primaryAction(
					"重新获取验证邮件",
					"verify-resend",
					() => {
						if (email === "") {
							navigate("/register");
							return;
						}
						void doResend();
					},
				);
				if (invalid) {
					wrap.replaceChildren(
						icon,
						header(
							"验证您的邮箱",
							"验证链接已过期或已被使用（时效 24 小时且限单次使用）。",
						),
						feedbackBar("danger", "该验证链接已失效，请重新获取验证邮件。"),
						relink,
					);
					return;
				}
			}
			wrap.replaceChildren(
				header(
					"验证您的邮箱",
					"验证过程中遇到了一些问题，请稍后再试或重新获取验证邮件。",
				),
				feedbackBar("danger", "验证失败，请稍后再试。"),
				primaryAction("返回登录", "verify-go-login", () => navigate("/login")),
			);
		}
		return;
	}

	// 引导页（无 token）：展示重发倒计时 + 受限模式入口。
	let cooldownSeconds = 0;
	const wrap = document.createElement("div");
	wrap.style.textAlign = "center";
	const icon = document.createElement("div");
	icon.style.marginBottom = "14px";
	icon.innerHTML = AUTH_ICONS.envelope;

	const desc = document.createElement("p");
	desc.className = "card-description";
	if (email !== "") {
		const strong = document.createElement("strong");
		strong.textContent = email;
		desc.append(
			document.createTextNode("激活链接已发送至 "),
			strong,
			document.createTextNode("，单次有效且时效为 24 小时。"),
		);
	} else {
		desc.textContent = "请使用注册时收到的邮件中的激活链接完成验证。";
	}

	const headerEl = header("验证您的邮箱", "");
	headerEl.replaceChildren();
	const h = document.createElement("h2");
	h.className = "card-title";
	h.textContent = "验证您的邮箱";
	headerEl.append(h, desc);

	const resend = primaryAction(
		"重新发送验证邮件",
		"verify-resend",
		() => void doResend(),
	);
	resend.type = "button";

	const feedbackSlot = document.createElement("div");
	const secondary = secondaryButton(
		"先进入工作台（受限模式）",
		() => navigate("/workspace"),
		"verify-enter-workspace",
	);
	const footer = document.createElement("div");
	footer.className = "card-footer";
	footer.append(document.createTextNode("使用其他账号？"));
	const switchAccount = document.createElement("a");
	switchAccount.textContent = "退出并切换";
	switchAccount.href = "/login";
	footer.append(switchAccount);

	wrap.append(icon, headerEl, feedbackSlot, resend, secondary, footer);
	renderSingle(wrap);

	async function doResend(): Promise<void> {
		if (email === "" || resend.disabled) return;
		setLoading(resend, true, "重新发送");
		feedbackSlot.replaceChildren();
		try {
			const result = await client.resendVerification({ email });
			const nextAt = Date.parse(result.nextAllowedAt);
			cooldownSeconds = Number.isFinite(nextAt)
				? Math.max(0, Math.ceil((nextAt - Date.now()) / 1000))
				: 60;
			startCountdown(cooldownSeconds, (remaining) => {
				resend.disabled = remaining > 0;
				resend.replaceChildren();
				const span = document.createElement("span");
				span.textContent =
					remaining > 0
						? `重新发送验证邮件（${remaining}s）`
						: "重新发送验证邮件";
				resend.append(span);
			});
		} catch (cause) {
			setLoading(resend, false, "重新发送验证邮件");
			if (cause instanceof DomApiError && cause.errorCode === "RATE_LIMITED") {
				feedbackSlot.replaceChildren(
					feedbackBar("warning", "请求较频繁，请稍候再试。"),
				);
			} else {
				feedbackSlot.replaceChildren(
					feedbackBar("danger", "重发失败，请稍后再试。"),
				);
			}
		}
	}
}
