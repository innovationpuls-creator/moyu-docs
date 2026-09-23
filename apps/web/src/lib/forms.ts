/**
 * Shared form helpers for the minimal web auth surface. UI/UX neutral:
 * functional labels + default inputs, no visual design decisions.
 */

export function emailInput(): HTMLInputElement {
	const input = document.createElement("input");
	input.type = "email";
	input.name = "email";
	input.autocomplete = "email";
	input.required = true;
	input.dataset.testid = "email-input";
	return input;
}

export function passwordInput(): HTMLInputElement {
	const input = document.createElement("input");
	input.type = "password";
	input.name = "password";
	input.autocomplete = "current-password";
	input.required = true;
	input.dataset.testid = "password-input";
	return input;
}

export function submitButton(label: string, testId: string): HTMLButtonElement {
	const button = document.createElement("button");
	button.type = "submit";
	button.textContent = label;
	button.dataset.testid = testId;
	return button;
}

export function fieldRow(
	label: string,
	input: HTMLInputElement,
): HTMLLabelElement {
	const row = document.createElement("label");
	row.textContent = label;
	row.append(input);
	return row;
}

export function errorText(): HTMLParagraphElement {
	const p = document.createElement("p");
	p.dataset.testid = "form-error";
	p.hidden = true;
	return p;
}
