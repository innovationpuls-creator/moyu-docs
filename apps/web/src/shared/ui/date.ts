export function formatConsoleDate(value: string | null | undefined): string {
	if (!value) return "时间未知";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "时间未知";
	return new Intl.DateTimeFormat("zh-CN", {
		month: "numeric",
		day: "numeric",
		hour: "2-digit",
		minute: "2-digit",
	}).format(date);
}
