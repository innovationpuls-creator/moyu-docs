/**
 * B 组管理台/编辑器壳的 DOM 原语与自绘 SVG 图标（ADR-0051：纯 CSS 变量 +
 * 原生 TS DOM；零 emoji，图标全部内联自绘，延续 A 组 1.8–2.2px 笔触风格）。
 *
 * 页面（workspace/editor）只在这里拿原语，不重复造轮子；数据字段强类型由
 * @dom/client-sdk 提供。
 */

/** 自绘 SVG 图标库（stroke 风格，currentColor 着色）。 */
const ICON_PATHS: Record<string, string> = {
	workspace:
		'<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
	search:
		'<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
	bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
	chevron: '<polyline points="9 18 15 12 9 6"/>',
	plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
	folder:
		'<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
	trash:
		'<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
	back: '<polyline points="15 18 9 12 15 6"/>',
	document:
		'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
	code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
	markdown:
		'<path d="M4 4h16v16H4z"/><path d="M7 15V9l3 3 3-3v6"/><path d="m14 13 2 2 2-2"/><path d="M16 9v6"/>',
	text: '<path d="M4 7V4h16v3"/><line x1="12" y1="4" x2="12" y2="20"/><line x1="8" y1="20" x2="16" y2="20"/>',
	comment:
		'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
	history:
		'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	sparkles:
		'<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
	panel:
		'<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="15" y1="3" x2="15" y2="21"/>',
	logout:
		'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
};

export type ConsoleIconName = keyof typeof ICON_PATHS;

/** 生成一个自绘 SVG 图标元素（stroke=currentColor，可指定尺寸）。 */
export function svgIcon(name: ConsoleIconName, size = 16): SVGSVGElement {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("width", String(size));
	svg.setAttribute("height", String(size));
	svg.setAttribute("viewBox", "0 0 24 24");
	svg.setAttribute("fill", "none");
	svg.setAttribute("stroke", "currentColor");
	svg.setAttribute("stroke-width", "2");
	svg.setAttribute("stroke-linecap", "round");
	svg.setAttribute("stroke-linejoin", "round");
	svg.innerHTML = ICON_PATHS[name];
	return svg;
}

/** 资源类型 → 图标元素 + 配色 class（document/code/markdown/text）。 */
export function resourceTypeIcon(
	type: "document" | "code" | "markdown" | "text",
	size = 22,
): { icon: SVGSVGElement; className: string } {
	const icon = svgIcon(type === "text" ? "text" : type, size);
	return { icon, className: `type-${type}` };
}

/** 创建一个下拉浮层（默认折叠；调用方负责挂到一个 position:relative 父级）。 */
export function makeDropdown(minWidth = 220): HTMLDivElement {
	const pop = document.createElement("div");
	pop.className = "dropdown-popover";
	pop.style.minWidth = `${minWidth}px`;
	return pop;
}

/** 共享的毛玻璃拼贴画布（全局一次挂载）。 */
export function createPatchwork(): HTMLElement {
	const canvas = document.createElement("div");
	canvas.className = "console-patchwork";
	for (let i = 1; i <= 3; i += 1) {
		const shape = document.createElement("div");
		shape.className = `patchwork-shape-${i}`;
		canvas.append(shape);
	}
	return canvas;
}

export interface EmptyStateOptions {
	title: string;
	description: string;
	/** 插画 SVG 元素（自绘，任意尺寸由 CSS 控制）。 */
	illustration: SVGElement;
	/** 动作区（按钮）。 */
	actions?: HTMLElement[];
	/** 插入到空态卡容器内（可选扩展）。 */
	extra?: HTMLElement[];
}

/** 空态卡片（柔和虚线卡 + 自绘插画 + 温和文案 + 引导动作）。 */
export function emptyStateCard(options: EmptyStateOptions): HTMLElement {
	const card = document.createElement("div");
	card.className = "empty-state-card";
	options.illustration.classList.add("empty-illustration");
	card.append(options.illustration);
	const title = document.createElement("h3");
	title.className = "empty-title";
	title.textContent = options.title;
	const desc = document.createElement("p");
	desc.className = "empty-desc";
	desc.textContent = options.description;
	card.append(title, desc);
	if (options.actions && options.actions.length > 0) {
		const actions = document.createElement("div");
		actions.style.display = "flex";
		actions.style.gap = "10px";
		actions.style.flexWrap = "wrap";
		actions.style.justifyContent = "center";
		actions.append(...options.actions);
		card.append(actions);
	}
	if (options.extra) card.append(...options.extra);
	return card;
}

/** 空态自绘插画 —— 无工作区（岛屿日出）。 */
export function illustrationNoWorkspace(): SVGElement {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("viewBox", "0 0 160 160");
	svg.setAttribute("fill", "none");
	svg.innerHTML = `
		<circle cx="80" cy="80" r="64" fill="var(--color-block-cream)"/>
		<path d="M48 100c12-8 32-12 64-4s32 18 16 26-64 4-80-6 0-16 0-16z" fill="var(--color-block-peach)" opacity="0.8"/>
		<circle cx="68" cy="62" r="14" fill="var(--color-block-sun)" opacity="0.9"/>
		<path d="M80 50v24M70 62h20" stroke="var(--color-block-terracotta)" stroke-width="2.5" stroke-linecap="round"/>`;
	return svg;
}

/** 空态自绘插画 —— 项目空书架。 */
export function illustrationNoProjects(): SVGElement {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("viewBox", "0 0 160 160");
	svg.setAttribute("fill", "none");
	svg.innerHTML = `
		<rect x="36" y="44" width="88" height="72" rx="14" fill="var(--color-block-cream)" stroke="var(--border-card)" stroke-width="2"/>
		<path d="M52 64h44M52 78h56M52 92h28" stroke="var(--color-block-terracotta)" stroke-width="2" stroke-linecap="round" opacity="0.6"/>
		<circle cx="110" cy="100" r="16" fill="var(--color-block-sage)" opacity="0.85"/>
		<path d="M110 94v12M104 100h12" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>`;
	return svg;
}

/** 空态自绘插画 —— 空白文稿。 */
export function illustrationNoResources(): SVGElement {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("viewBox", "0 0 160 160");
	svg.setAttribute("fill", "none");
	svg.innerHTML = `
		<ellipse cx="80" cy="115" rx="50" ry="16" fill="var(--color-block-peach)" opacity="0.5"/>
		<rect x="52" y="40" width="56" height="74" rx="8" fill="#ffffff" stroke="var(--border-card)" stroke-width="2"/>
		<path d="M64 58h32M64 72h24M64 86h28" stroke="var(--ink-muted)" stroke-width="2" stroke-linecap="round" opacity="0.4"/>
		<circle cx="106" cy="46" r="10" fill="var(--color-block-sun)"/>`;
	return svg;
}
