/**
 * A 组未登录界面（墨屿 · Moyu Docs 视觉基线，ADR-0051）冒烟测试。
 *
 * 覆盖：路由守卫落 /login、品牌壳与 E2E testid 契约、登录防枚举文案、
 * 找回密码绝对防枚举、重置/验证深链的失效与空态。全部走真实后端（API
 * 由 playwright webServer 拉起，:8000；网关 :8765 复用）。
 */

import { expect, test } from "@playwright/test";

test("A1: 未知路径重定向 /login，品牌壳与表单 testid 契约渲染", async ({
	page,
}) => {
	await page.goto("/no-such-page");
	await expect(page).toHaveURL(/\/login$/);
	await expect(page.getByTestId("login-form")).toBeVisible();
	await expect(page.getByTestId("email-input")).toBeVisible();
	await expect(page.getByTestId("password-input")).toBeVisible();
	await expect(page.getByTestId("login-submit")).toBeVisible();
	await expect(page.getByText("墨屿 · Moyu Docs")).toBeVisible();
});

test("A2: 登录失败展示统一防枚举文案（INVALID_CREDENTIALS）", async ({
	page,
}) => {
	await page.goto("/login");
	const email = `nobody-${Date.now()}@example.com`;
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("password-input").fill("wrong-password-123456");
	await page.getByTestId("password-input").press("Enter");
	await expect(page.getByText(/邮箱或密码不正确/)).toBeVisible();
});

test("A3: 找回密码绝对防枚举，未知邮箱也返回成功安抚", async ({ page }) => {
	await page.goto("/forgot-password");
	const email = `nobody-${Date.now()}@example.com`;
	await page.getByTestId("email-input").fill(email);
	await page.getByTestId("forgot-submit").click();
	await expect(
		page.getByText(/邮件已发出！若邮箱已注册，请在 15 分钟内查收/),
	).toBeVisible();
});

test("A4: 重置密码无 token 深链 → 失效引导 + 重新申请", async ({ page }) => {
	await page.goto("/reset-password");
	await expect(page.getByTestId("reset-request-again")).toBeVisible();
	await expect(page.getByText(/重置链接已失效/)).toBeVisible();
});

test("A5: 验证引导页无会话无 token → 空态引导登录", async ({ page }) => {
	await page.goto("/verify-email");
	await expect(page.getByTestId("verify-go-login")).toBeVisible();
	await expect(page.getByText(/未找到待验证的账号/)).toBeVisible();
});
