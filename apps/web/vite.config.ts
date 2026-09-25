import { defineConfig } from "vite";

export default defineConfig({
	build: {
		manifest: "asset-manifest.json",
	},
	// The web dev server proxies /v1 to the API service so the typed client
	// (packages/ts/client-sdk) talks same-origin (no CORS), and cookies set
	// by the API (dom_session/dom_device) are recorded on the web origin.
	server: {
		port: 5173,
		strictPort: true,
		host: "localhost",
		proxy: {
			"/v1": {
				target: "http://127.0.0.1:8000",
				changeOrigin: false,
			},
		},
	},
});
