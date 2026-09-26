import { expect, test } from "@playwright/test";

test("reduced-motion preference disables console animations and transitions", async ({
	page,
}) => {
	await page.emulateMedia({ reducedMotion: "no-preference" });
	await page.goto("/login");

	const appendMotionProbes = async () =>
		page.evaluate(() => {
			const dot = document.createElement("span");
			dot.className = "roster-dot";
			document.body.append(dot);
			const button = document.createElement("button");
			button.className = "ws-switcher-btn";
			document.body.append(button);

			const dotStyle = getComputedStyle(dot);
			const buttonStyle = getComputedStyle(button);
			const result = {
				animationName: dotStyle.animationName,
				animationDuration: dotStyle.animationDuration,
				transitionDuration: buttonStyle.transitionDuration,
			};
			dot.remove();
			button.remove();
			return result;
		});

	const normalMotion = await appendMotionProbes();
	expect(normalMotion.animationName).toBe("pulse-dot");
	expect(normalMotion.animationDuration).toBe("2s");
	expect(normalMotion.transitionDuration).toContain("0.18s");

	await page.emulateMedia({ reducedMotion: "reduce" });
	const reducedMotion = await appendMotionProbes();
	expect(reducedMotion.animationName).toBe("none");
	expect(reducedMotion.transitionDuration).toBe("0s");
});
