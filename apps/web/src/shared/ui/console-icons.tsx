export type ConsoleIconName =
	| "workspace"
	| "search"
	| "bell"
	| "folder"
	| "document"
	| "code"
	| "markdown"
	| "text"
	| "trash"
	| "chevron"
	| "chevronDown"
	| "plus"
	| "menu"
	| "arrowLeft"
	| "panel"
	| "comments"
	| "history"
	| "sparkle";

export type ResourceType = "document" | "code" | "markdown" | "text";

const paths: Record<ConsoleIconName, string[]> = {
	workspace: ["M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"],
	search: ["m20 20-4.4-4.4", "M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z"],
	bell: ["M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9", "M10 21h4"],
	folder: ["M3 6h7l2 2h9v10H3z"],
	document: ["M6 3h8l4 4v14H6z", "M14 3v5h5", "M9 12h6", "M9 16h6"],
	code: ["m8 8-4 4 4 4", "m16 8 4 4-4 4", "m14 5-4 14"],
	markdown: ["M4 5h16v14H4z", "M7 15V9l3 3 3-3v6", "M16 10v5m-2-2 2 2 2-2"],
	text: ["M5 5h14", "M12 5v14", "M8 19h8"],
	trash: ["M4 7h16", "M9 7V4h6v3m3 0-1 14H7L6 7"],
	chevron: ["m9 18 6-6-6-6"],
	chevronDown: ["m6 9 6 6 6-6"],
	plus: ["M12 5v14", "M5 12h14"],
	menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
	arrowLeft: ["m15 18-6-6 6-6", "M9 12h12"],
	panel: ["M3 4h18v16H3z", "M15 4v16"],
	comments: ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"],
	history: ["M3 12a9 9 0 1 0 2.6-6.4L3 8", "M3 3v5h5", "M12 7v5l3 2"],
	sparkle: [
		"m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z",
		"m19 15 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z",
	],
};

export function ConsoleIcon({
	name,
	size = 16,
}: {
	name: ConsoleIconName;
	size?: number;
}) {
	return (
		<svg
			className="console-icon"
			width={size}
			height={size}
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.8"
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
		>
			{paths[name].map((path) => (
				<path d={path} key={path} />
			))}
		</svg>
	);
}

export function ResourceTypeIcon({ type }: { type: ResourceType }) {
	return (
		<span className={`resource-type-icon type-${type}`} aria-hidden="true">
			<ConsoleIcon name={type} size={16} />
		</span>
	);
}
