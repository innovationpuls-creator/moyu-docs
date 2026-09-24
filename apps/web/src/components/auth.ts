/**
 * 墨屿 · Moyu Docs 未登录界面组（A 组）共享组件原语（ADR-0051，spec §4）。
 *
 * 全部为纯 DOM 构建器，样式只走 src/styles/auth.css 的 CSS Variables；
 * 不在此层发起 fetch/WebSocket（页面负责 SDK 调用）；所有 E2E 依赖的
 * data-testid 契约经选项透传（browser_session_semantics.spec.ts）。
 */

/** 自研纯 SVG 矢量图标集（spec：纯 SVG 图标，零 Emoji 策略）。 */
export const AUTH_ICONS = {
	eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`,
	info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
	clock: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
	check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="9 12 11 14 15 10"/></svg>`,
	envelope: `<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="20" height="16" x="2" y="4" rx="3"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>`,
	wifiOff: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m2 2 20 20"/><path d="M8.5 8.5a6 6 0 0 1 8.5 0"/><path d="M5 5a10 10 0 0 1 14 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>`,
	brandDot: `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="6"/></svg>`,
} as const;

function el<K extends keyof HTMLElementTagNameMap>(
	tag: K,
	className?: string,
): HTMLElementTagNameMap[K] {
	const node = document.createElement(tag);
	if (className !== undefined) {
		node.className = className;
	}
	return node;
}

function iconSpan(svg: string): HTMLElement {
	const span = document.createElement("span");
	span.innerHTML = svg;
	return span;
}

/** 55:45 主舞台壳：拼色画布 + 品牌叙事区 + 毛玻璃认证面板 + 离线通告条。 */
export interface AuthShell {
	root: HTMLElement;
	card: HTMLElement;
	notice: HTMLElement;
}

export function createAuthShell(): AuthShell {
	const root = el("main", "split-stage");

	const canvas = el("div", "patchwork-canvas");
	for (const shape of [
		"patchwork-shape-1",
		"patchwork-shape-2",
		"patchwork-shape-3",
		"patchwork-shape-4",
		"patchwork-shape-sun",
	]) {
		canvas.append(el("div", shape));
	}

	const art = el("section", "art-panel");
	art.setAttribute("aria-label", "品牌与架构叙事");
	const top = el("div", "art-content-top");
	const badge = el("div", "brand-pill-badge");
	badge.append(iconSpan(AUTH_ICONS.brandDot));
	const badgeText = document.createElement("span");
	badgeText.textContent = "墨屿 · Moyu Docs";
	badge.append(badgeText);

	const headline = el("h1", "art-headline");
	headline.append(
		document.createTextNode("以结构组织思考，"),
		document.createElement("br"),
		document.createTextNode("专注、轻盈、本地优先。"),
	);
	const subline = el("p", "art-subline");
	subline.textContent =
		"墨屿（Moyu Docs）是一款本地优先的团队协同文档软件。像笔记一样轻盈灵敏、断网即开即写；像现代工作台一样多人无冲突实时共笔，让思考与协作从容推进。";
	top.append(badge, headline, subline);

	const bottom = el("div", "art-content-bottom");
	const tags = el("div", "brand-subtle-tag");
	for (const [i, text] of ["本地优先", "实时共笔", "团队协同文档"].entries()) {
		if (i > 0) {
			const dot = document.createElement("span");
			dot.className = "dot";
			dot.textContent = "·";
			tags.append(dot);
		}
		const span = document.createElement("span");
		span.textContent = text;
		tags.append(span);
	}
	bottom.append(tags);
	art.append(top, bottom);

	const notice = el("div", "offline-notice");
	notice.append(iconSpan(AUTH_ICONS.wifiOff));
	const noticeText = document.createElement("span");
	noticeText.textContent = "网络连接暂时中断，恢复后将自动继续";
	notice.append(noticeText);

	const panel = el("section", "auth-panel");
	panel.setAttribute("aria-label", "用户认证交互区");
	const card = el("div", "auth-card-inner");
	panel.append(card);

	root.append(notice, canvas, art, panel);
	return { root, card, notice };
}

/** 认证卡片标题区。 */
export function cardHeader(
	title: string,
	description: string,
	opts: { centered?: boolean } = {},
): HTMLElement {
	const header = el("div", "card-header");
	if (opts.centered === true) {
		header.style.textAlign = "center";
	}
	const h = el("h2", "card-title");
	h.textContent = title;
	const p = el("p", "card-description");
	p.textContent = description;
	header.append(h, p);
	return header;
}

/** 表单字段组：label 行（可带行内链接）+ 输入包裹层。 */
export function formGroup(
	labelText: string,
	opts: { forId?: string; link?: { text: string; href: string } } = {},
): { group: HTMLElement; label: HTMLLabelElement; wrapper: HTMLElement } {
	const group = el("div", "form-group");
	const labelRow = el("div", "form-label-row");
	const label = document.createElement("label");
	label.className = "form-label";
	label.textContent = labelText;
	if (opts.forId !== undefined) {
		label.htmlFor = opts.forId;
	}
	labelRow.append(label);
	if (opts.link !== undefined) {
		const a = document.createElement("a");
		a.className = "form-label-link";
		a.textContent = opts.link.text;
		a.href = opts.link.href;
		labelRow.append(a);
	}
	const wrapper = el("div", "input-wrapper");
	group.append(labelRow, wrapper);
	return { group, label, wrapper };
}

/** 文本/邮箱输入框（data-testid 透传，class=auth-input）。 */
export function textInput(opts: {
	testId?: string;
	type?: string;
	placeholder?: string;
	autocomplete?: string;
	required?: boolean;
}): HTMLInputElement {
	const input = document.createElement("input");
	input.className = "auth-input";
	input.type = opts.type ?? "text";
	if (opts.placeholder !== undefined) input.placeholder = opts.placeholder;
	if (opts.autocomplete !== undefined) {
		input.setAttribute("autocomplete", opts.autocomplete);
	}
	if (opts.required === true) input.required = true;
	if (opts.testId !== undefined) input.dataset.testid = opts.testId;
	return input;
}

/** 密码显隐切换按钮（input-addon-btn，44px 热区）。 */
export function passwordToggle(input: HTMLInputElement): HTMLButtonElement {
	const button = document.createElement("button");
	button.type = "button";
	button.className = "input-addon-btn";
	button.setAttribute("aria-label", "切换密码明暗文");
	button.append(iconSpan(AUTH_ICONS.eye));
	button.addEventListener("click", () => {
		input.type = input.type === "password" ? "text" : "password";
	});
	return button;
}

/** 字段辅助提示（field-hint error|success）。 */
export function fieldHint(
	kind: "error" | "success",
	text: string,
): HTMLElement {
	const hint = el("div", `field-hint ${kind}`);
	hint.textContent = text;
	hint.hidden = true;
	return hint;
}

/** 反馈气泡条（feedback-bar danger|warning|success）。 */
export function feedbackBar(
	kind: "danger" | "warning" | "success",
	text: string,
): HTMLElement {
	const bar = el("div", `feedback-bar ${kind}`);
	const icon =
		kind === "danger"
			? AUTH_ICONS.info
			: kind === "warning"
				? AUTH_ICONS.clock
				: AUTH_ICONS.check;
	bar.append(iconSpan(icon));
	const span = document.createElement("span");
	span.textContent = text;
	bar.append(span);
	return bar;
}

/** 主按钮（btn-pill primary；data-testid 透传）。 */
export function primaryButton(
	label: string,
	testId: string,
): HTMLButtonElement {
	const button = document.createElement("button");
	button.type = "submit";
	button.className = "btn-pill primary";
	const span = document.createElement("span");
	span.textContent = label;
	button.append(span);
	button.dataset.testid = testId;
	return button;
}

/** 次级按钮（btn-pill secondary）。 */
export function secondaryButton(
	label: string,
	onClick: () => void,
	id?: string,
): HTMLButtonElement {
	const button = document.createElement("button");
	button.type = "button";
	button.className = "btn-pill secondary";
	button.textContent = label;
	button.addEventListener("click", onClick);
	if (id !== undefined) {
		button.dataset.testid = id;
	}
	return button;
}

/** 切换主按钮 loading 态（细圈 Spinner + 防重复点击）。 */
export function setLoading(
	button: HTMLButtonElement,
	loading: boolean,
	label: string,
): void {
	button.disabled = loading;
	button.replaceChildren();
	if (loading) {
		button.append(el("div", "spinner"));
		const span = el("span", "btn-text-loading");
		span.textContent = label;
		button.append(span);
	} else {
		const span = document.createElement("span");
		span.textContent = label;
		button.append(span);
	}
}

/** 卡片底部行（card-footer：前缀 + 链接）。 */
export function footerText(
	prefix: string,
	anchorText: string,
	href: string,
	testId?: string,
): HTMLElement {
	const footer = el("div", "card-footer");
	footer.append(document.createTextNode(prefix));
	const a = document.createElement("a");
	a.textContent = anchorText;
	a.href = href;
	if (testId !== undefined) a.dataset.testid = testId;
	footer.append(a);
	return footer;
}

/** 无惩罚感轻微晃动（错误提交时替代红屏抖动）。 */
export function gentleShake(card: HTMLElement): void {
	card.classList.remove("gentle-shake");
	void card.offsetWidth;
	card.classList.add("gentle-shake");
}

/** 离线/在线状态绑定：切换通告条并回调按钮可用性。 */
export function bindOffline(
	notice: HTMLElement,
	onChange: (offline: boolean) => void,
): () => void {
	const update = (): void => {
		const offline = !navigator.onLine;
		notice.classList.toggle("show", offline);
		onChange(offline);
	};
	window.addEventListener("offline", update);
	window.addEventListener("online", update);
	update();
	return () => {
		window.removeEventListener("offline", update);
		window.removeEventListener("online", update);
	};
}

/** 每秒倒计时，onTick(剩余秒)。返回 stop()。 */
export function startCountdown(
	seconds: number,
	onTick: (remaining: number) => void,
): () => void {
	let remaining = Math.max(0, Math.round(seconds));
	onTick(remaining);
	const timer = window.setInterval(() => {
		remaining -= 1;
		if (remaining <= 0) {
			window.clearInterval(timer);
			onTick(0);
			return;
		}
		onTick(remaining);
	}, 1000);
	return () => window.clearInterval(timer);
}

/** 秒数 → mm:ss（锁定时钟胶囊用）。 */
export function formatLockout(seconds: number): string {
	const m = Math.floor(seconds / 60);
	const s = seconds % 60;
	return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
