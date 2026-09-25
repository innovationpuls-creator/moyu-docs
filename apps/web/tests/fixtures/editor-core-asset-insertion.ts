import { createTextDocument } from "@dom/editor-core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { AssetsPanel } from "../../src/features/assets/index.js";

interface AssetInsertionHarness {
	read(): {
		text: string;
		markup: string;
		events: string[];
		updateCount: number;
		peerText: string;
		wasFocusedAtMount: boolean;
		focusedAfterInsertion: boolean;
	};
	insertDirectly(): void;
	destroy(): void;
}

declare global {
	interface Window {
		__assetInsertionHarness?: AssetInsertionHarness;
	}
}

export function mountAssetPanelInsertion(): void {
	const panelHost = window.document.createElement("div");
	const editorHost = window.document.createElement("div");
	window.document.body.append(panelHost, editorHost);
	const document = createTextDocument();
	document.setText("现有正文");
	document.flushLocalUpdates();
	const events: string[] = [];
	const unsubscribe = document.onTextChange((text) => events.push(text));
	const surface = document.mountEditor(editorHost);
	const wasFocusedAtMount = editorHost.contains(window.document.activeElement);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	const root = createRoot(panelHost);
	root.render(
		createElement(
			QueryClientProvider,
			{ client: queryClient },
			createElement(AssetsPanel, {
				resourceId: "asset-insertion-test-resource",
				onInsertAssets: (references) => surface.insertAssets(references),
			}),
		),
	);
	window.__assetInsertionHarness = {
		insertDirectly: () =>
			surface.insertAssets([
				{
					kind: "image",
					assetId: "asset-mounted-image",
					label: "diagram.png",
				},
			]),
		read: () => {
			const peer = createTextDocument(document.exportState());
			const peerText = peer.getText();
			peer.destroy();
			return {
				text: document.getText(),
				markup: editorHost.querySelector(".ProseMirror")?.innerHTML ?? "",
				events,
				updateCount: events.length,
				peerText,
				wasFocusedAtMount,
				focusedAfterInsertion: editorHost.contains(
					window.document.activeElement,
				),
			};
		},
		destroy: () => {
			root.unmount();
			queryClient.clear();
			unsubscribe();
			surface.destroy();
			document.destroy();
			panelHost.remove();
			editorHost.remove();
			delete window.__assetInsertionHarness;
		},
	};
}

export function mountUnfocusedEditorInsertion(): void {
	const editorHost = window.document.createElement("div");
	window.document.body.append(editorHost);
	const document = createTextDocument();
	document.setText("现有正文");
	document.flushLocalUpdates();
	const events: string[] = [];
	const unsubscribe = document.onTextChange((text) => events.push(text));
	const surface = document.mountEditor(editorHost);
	const wasFocusedAtMount = editorHost.contains(window.document.activeElement);
	window.__assetInsertionHarness = {
		insertDirectly: () =>
			surface.insertAssets([
				{
					kind: "image",
					assetId: "asset-direct-image",
					label: "direct.png",
				},
			]),
		read: () => {
			const peer = createTextDocument(document.exportState());
			const peerText = peer.getText();
			peer.destroy();
			return {
				text: document.getText(),
				markup: editorHost.querySelector(".ProseMirror")?.innerHTML ?? "",
				events,
				updateCount: events.length,
				peerText,
				wasFocusedAtMount,
				focusedAfterInsertion: editorHost.contains(
					window.document.activeElement,
				),
			};
		},
		destroy: () => {
			unsubscribe();
			surface.destroy();
			document.destroy();
			editorHost.remove();
			delete window.__assetInsertionHarness;
		},
	};
}

export function readAssetPanelInsertion() {
	return window.__assetInsertionHarness?.read() ?? null;
}
