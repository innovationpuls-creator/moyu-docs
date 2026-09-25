/** Full-page navigation bridge used only by the preserved legacy auth forms. */
export function navigate(path: string): void {
	window.location.assign(path);
}
