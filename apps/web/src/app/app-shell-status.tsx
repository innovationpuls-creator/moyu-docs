import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import "./app-shell.css";

export function AppShellStatus() {
	const queryClient = useQueryClient();
	const [offline, setOffline] = useState(() => navigator.onLine === false);
	const [connectionUnavailable, setConnectionUnavailable] = useState(false);
	const [updateReady, setUpdateReady] = useState(false);
	const [shellUnavailable, setShellUnavailable] = useState(false);
	const registration = useRef<ServiceWorkerRegistration | null>(null);

	useEffect(() => {
		const handleOnline = () => {
			setOffline(false);
			setConnectionUnavailable(false);
		};
		const handleOffline = () => {
			setOffline(true);
			setConnectionUnavailable(false);
		};
		const unsubscribeQueries = queryClient
			.getQueryCache()
			.subscribe((event) => {
				if (event.type !== "updated") return;
				if (
					event.action.type === "error" &&
					event.query.state.error instanceof TypeError
				) {
					setConnectionUnavailable(true);
				} else if (event.action.type === "success") {
					setConnectionUnavailable(false);
				}
			});
		window.addEventListener("online", handleOnline);
		window.addEventListener("offline", handleOffline);
		if (!("serviceWorker" in navigator) || !import.meta.env.PROD) {
			return () => {
				unsubscribeQueries();
				window.removeEventListener("online", handleOnline);
				window.removeEventListener("offline", handleOffline);
			};
		}

		let disposed = false;
		let updateFoundHandler: (() => void) | null = null;
		let controllerChangeHandler: (() => void) | null = null;
		const hadController = Boolean(navigator.serviceWorker.controller);

		void navigator.serviceWorker
			.register("/service-worker.js", { scope: "/" })
			.then((currentRegistration) => {
				if (disposed) return;
				registration.current = currentRegistration;
				if (hadController && currentRegistration.waiting) {
					setUpdateReady(true);
				}
				updateFoundHandler = () => {
					const installing = currentRegistration.installing;
					installing?.addEventListener("statechange", () => {
						if (
							installing.state === "installed" &&
							hadController &&
							navigator.serviceWorker.controller
						) {
							setUpdateReady(true);
						}
					});
				};
				controllerChangeHandler = () => {
					if (hadController) setUpdateReady(true);
				};
				currentRegistration.addEventListener("updatefound", updateFoundHandler);
				navigator.serviceWorker.addEventListener(
					"controllerchange",
					controllerChangeHandler,
				);
			})
			.catch(() => {
				setShellUnavailable(true);
			});

		return () => {
			disposed = true;
			unsubscribeQueries();
			window.removeEventListener("online", handleOnline);
			window.removeEventListener("offline", handleOffline);
			if (updateFoundHandler) {
				registration.current?.removeEventListener(
					"updatefound",
					updateFoundHandler,
				);
			}
			if (controllerChangeHandler) {
				navigator.serviceWorker.removeEventListener(
					"controllerchange",
					controllerChangeHandler,
				);
			}
		};
	}, [queryClient]);

	function applyUpdate() {
		const waiting = registration.current?.waiting;
		if (waiting) {
			waiting.postMessage({ type: "ACTIVATE_UPDATE" });
			return;
		}
		window.location.reload();
	}

	if (!offline && !connectionUnavailable && !updateReady && !shellUnavailable)
		return null;
	return (
		<aside className="app-shell-status" role="status" aria-live="polite">
			{(offline || connectionUnavailable) && (
				<span data-testid="app-offline-status">
					{offline ? "网络状态：离线" : "网络状态：无法连接服务"}
				</span>
			)}
			{updateReady && (
				<span>
					应用更新已准备好。
					<button
						type="button"
						className="app-shell-status-action"
						onClick={applyUpdate}
					>
						{registration.current?.waiting ? "启用并刷新" : "刷新页面"}
					</button>
				</span>
			)}
			{shellUnavailable && (
				<span data-testid="app-shell-cache-error">离线启动缓存不可用</span>
			)}
		</aside>
	);
}
