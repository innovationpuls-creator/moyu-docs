import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { AssetsPanel } from "../../src/features/assets/index.js";

interface AssetsPanelHarness {
	destroy(): void;
}

declare global {
	interface Window {
		__assetsPanelHarness?: AssetsPanelHarness;
	}
}

export function mountAssetsPanel(): void {
	const host = window.document.createElement("div");
	window.document.body.append(host);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const root = createRoot(host);
	root.render(
		createElement(
			QueryClientProvider,
			{ client: queryClient },
			createElement(AssetsPanel, {
				resourceId: "asset-upload-idempotency-resource",
				onInsertAssets: () => undefined,
			}),
		),
	);
	window.__assetsPanelHarness = {
		destroy: () => {
			root.unmount();
			queryClient.clear();
			host.remove();
			delete window.__assetsPanelHarness;
		},
	};
}
