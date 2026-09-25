import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import {
	BrowserRouter,
	Navigate,
	Route,
	Routes,
	useLocation,
} from "react-router";
import { EditorPage } from "../features/editor";
import { WorkspacePage } from "../features/workspace";
import { renderForgotPasswordPage } from "../pages/forgot-password";
import { renderLoginPage } from "../pages/login";
import { renderRegisterPage } from "../pages/register";
import { renderResetPasswordPage } from "../pages/reset-password";
import { renderVerifyEmailPage } from "../pages/verify-email";
import { queryClient } from "../shared/api/query-client";

type LegacyRenderer = (root: HTMLElement) => void | Promise<void>;

function LegacyAuthPage({ render }: { render: LegacyRenderer }) {
	const root = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (root.current) void render(root.current);
	}, [render]);
	return <div ref={root} />;
}

function SurfaceScope() {
	const { pathname } = useLocation();
	useEffect(() => {
		const auth = [
			"/login",
			"/register",
			"/verify-email",
			"/forgot-password",
			"/reset-password",
		].includes(pathname);
		document.body.classList.toggle("auth-surface", auth);
		document.body.classList.toggle(
			"console-surface",
			pathname === "/workspace" || pathname === "/editor",
		);
	}, [pathname]);
	return null;
}

export function App() {
	return (
		<QueryClientProvider client={queryClient}>
			<BrowserRouter>
				<SurfaceScope />
				<Routes>
					<Route
						path="/login"
						element={<LegacyAuthPage render={renderLoginPage} />}
					/>
					<Route
						path="/register"
						element={<LegacyAuthPage render={renderRegisterPage} />}
					/>
					<Route
						path="/verify-email"
						element={<LegacyAuthPage render={renderVerifyEmailPage} />}
					/>
					<Route
						path="/forgot-password"
						element={<LegacyAuthPage render={renderForgotPasswordPage} />}
					/>
					<Route
						path="/reset-password"
						element={<LegacyAuthPage render={renderResetPasswordPage} />}
					/>
					<Route path="/workspace" element={<WorkspacePage />} />
					<Route path="/editor" element={<EditorPage />} />
					<Route path="*" element={<Navigate to="/login" replace />} />
				</Routes>
			</BrowserRouter>
		</QueryClientProvider>
	);
}
