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
	eyeOff: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/></svg>`,
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
	const line1Wrap = el("span", "headline-line-wrap");
	const line1Inner = el("span", "headline-line-inner");
	line1Inner.textContent = "以结构组织思考，";
	line1Wrap.append(line1Inner);

	const line2Wrap = el("span", "headline-line-wrap");
	const line2Inner = el("span", "headline-line-inner");
	line2Inner.textContent = "专注、轻盈、本地优先。";
	line2Wrap.append(line2Inner);

	headline.append(line1Wrap, line2Wrap);
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

/** 密码显隐切换按钮（input-addon-btn，44px 热区，带轻快回弹动效与明暗文图标切换）。 */
export function passwordToggle(input: HTMLInputElement): HTMLButtonElement {
	const button = document.createElement("button");
	button.type = "button";
	button.className = "input-addon-btn";
	button.setAttribute("aria-label", "切换密码明暗文");
	const iconContainer = iconSpan(AUTH_ICONS.eye);
	button.append(iconContainer);
	button.addEventListener("click", () => {
		const isPassword = input.type === "password";
		input.type = isPassword ? "text" : "password";
		iconContainer.innerHTML = isPassword ? AUTH_ICONS.eyeOff : AUTH_ICONS.eye;
		button.classList.add("toggled");
		window.setTimeout(() => button.classList.remove("toggled"), 240);
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

/**
 * 桌面端微重力指针流体视差与舞台 2.5D 透视联动（遵循 motion-web handfeel §7.1 单阶指数衰减平滑方程与 §2 速度耦合）。
 * 在 pointer: fine 桌面端捕获鼠标轨迹，驱动色块分层视差偏移与主舞台微透视倾斜。
 * 离开视口平滑归位；页面注销时返回清理函数。
 */
export function bindPatchworkParallax(stage: HTMLElement): () => void {
	if (
		typeof window === "undefined" ||
		!window.matchMedia("(pointer: fine)").matches ||
		window.matchMedia("(prefers-reduced-motion: reduce)").matches
	) {
		return () => {};
	}
	const shape1 = stage.querySelector<HTMLElement>(".patchwork-shape-1");
	const shape2 = stage.querySelector<HTMLElement>(".patchwork-shape-2");
	const shape3 = stage.querySelector<HTMLElement>(".patchwork-shape-3");
	const shape4 = stage.querySelector<HTMLElement>(".patchwork-shape-4");
	const shapeSun = stage.querySelector<HTMLElement>(".patchwork-shape-sun");

	if (!shape1 && !shape2 && !shape3 && !shape4 && !shapeSun) {
		return () => {};
	}

	let targetX = 0;
	let targetY = 0;
	let currentX = 0;
	let currentY = 0;
	let prevX = 0;
	let animId = 0;
	let lastTime = performance.now();
	let running = true;

	const onMouseMove = (event: MouseEvent): void => {
		const rect = stage.getBoundingClientRect();
		if (rect.width <= 0 || rect.height <= 0) return;
		const cx = rect.left + rect.width / 2;
		const cy = rect.top + rect.height / 2;
		targetX = Math.max(
			-1,
			Math.min(1, (event.clientX - cx) / (rect.width / 2)),
		);
		targetY = Math.max(
			-1,
			Math.min(1, (event.clientY - cy) / (rect.height / 2)),
		);
	};

	const onMouseLeave = (): void => {
		targetX = 0;
		targetY = 0;
	};

	// Handfeel §7.1 & §7.2: dt in seconds; K=5.4 buoyant, settling crisply within 240ms
	const K = 5.4;

	const loop = (now: number): void => {
		if (!running) return;
		const dt = Math.min((now - lastTime) / 1000, 0.05);
		lastTime = now;

		const factor = 1 - Math.exp(-K * dt);
		currentX += (targetX - currentX) * factor;
		currentY += (targetY - currentY) * factor;
		const velX = (currentX - prevX) / (dt || 0.016);
		prevX = currentX;

		// 1. 主舞台 2.5D 透视微倾斜（±1.6° ~ ±1.8°）
		const tiltX = (-currentY * 1.6).toFixed(2);
		const tiltY = (currentX * 1.8).toFixed(2);
		stage.style.setProperty("--tilt-x", `${tiltX}deg`);
		stage.style.setProperty("--tilt-y", `${tiltY}deg`);

		// 2. 色块 1 (深层暖桃): 微动 (-14px, -10px)
		shape1?.style.setProperty("--px", `${(currentX * -14).toFixed(2)}px`);
		shape1?.style.setProperty("--py", `${(currentY * -10).toFixed(2)}px`);

		// 3. 色块 2 (中层鼠尾草绿): (24px, 20px, 微旋转 1.6deg)
		shape2?.style.setProperty("--px", `${(currentX * 24).toFixed(2)}px`);
		shape2?.style.setProperty("--py", `${(currentY * 20).toFixed(2)}px`);
		shape2?.style.setProperty("--prot", `${(currentX * 1.6).toFixed(2)}deg`);

		// 4. 色块 3 (穿透中轴陶土珊瑚主色 · 前景核心): 层次大幅拉开 (-42px, -32px, 叠加速度耦合倾角)
		const lean3 = Math.max(-3.5, Math.min(3.5, velX * 0.45));
		shape3?.style.setProperty("--px", `${(currentX * -42).toFixed(2)}px`);
		shape3?.style.setProperty("--py", `${(currentY * -32).toFixed(2)}px`);
		shape3?.style.setProperty(
			"--prot",
			`${(currentX * -2.8 - lean3).toFixed(2)}deg`,
		);

		// 5. 色块 4 (薰衣草紫): (18px, -16px)
		shape4?.style.setProperty("--px", `${(currentX * 18).toFixed(2)}px`);
		shape4?.style.setProperty("--py", `${(currentY * -16).toFixed(2)}px`);

		// 6. 色块 5 (晨曦金环): 强烈向心引力 (32px, 28px) 与距离膨胀微感
		const dist = Math.hypot(currentX, currentY);
		shapeSun?.style.setProperty("--px", `${(currentX * 32).toFixed(2)}px`);
		shapeSun?.style.setProperty("--py", `${(currentY * 28).toFixed(2)}px`);
		shapeSun?.style.setProperty("--pscale", `${(1 + dist * 0.08).toFixed(3)}`);

		animId = requestAnimationFrame(loop);
	};

	window.addEventListener("mousemove", onMouseMove, { passive: true });
	document.addEventListener("mouseleave", onMouseLeave);
	animId = requestAnimationFrame(loop);

	return () => {
		running = false;
		cancelAnimationFrame(animId);
		window.removeEventListener("mousemove", onMouseMove);
		document.removeEventListener("mouseleave", onMouseLeave);
		stage.style.removeProperty("--tilt-x");
		stage.style.removeProperty("--tilt-y");
	};
}

/** 切换主按钮至成功态（绽放鼠尾草绿勾选印记）。 */
export function setSuccessButton(
	button: HTMLButtonElement,
	label = "登入成功，正在进入…",
): void {
	button.disabled = true;
	button.classList.add("btn-success");
	button.replaceChildren();
	const checkIcon = iconSpan(AUTH_ICONS.check);
	checkIcon.className = "btn-icon-check";
	const span = document.createElement("span");
	span.textContent = label;
	button.append(checkIcon, span);
}

/** 登录成功平滑退场过渡（光晕散开、舞台柔和缩退）。 */
export async function playAuthExit(root: HTMLElement): Promise<void> {
	if (
		typeof window === "undefined" ||
		window.matchMedia("(prefers-reduced-motion: reduce)").matches
	) {
		return;
	}
	root.classList.add("stage-exit");
	await new Promise((resolve) => setTimeout(resolve, 360));
}
