const CACHE_PREFIX = "dom-app-shell-";
const ASSET_MANIFEST_URL = "/asset-manifest.json";
const HASHED_ASSET = /^\/assets\/[^/]*(?:[-.])[A-Za-z0-9_-]{8,}\.(?:js|css)$/;

function hashVersion(value) {
	let hash = 2166136261;
	for (let index = 0; index < value.length; index += 1) {
		hash ^= value.charCodeAt(index);
		hash = Math.imul(hash, 16777619);
	}
	return (hash >>> 0).toString(16).padStart(8, "0");
}

function getHashedAssetPaths(manifest) {
	const paths = new Set();
	for (const entry of Object.values(manifest)) {
		if (!entry || typeof entry !== "object") continue;
		for (const file of [entry.file, ...(entry.css ?? [])]) {
			if (typeof file !== "string") continue;
			const url = new URL(file, self.location.origin);
			if (
				url.origin === self.location.origin &&
				HASHED_ASSET.test(url.pathname)
			) {
				paths.add(url.pathname);
			}
		}
	}
	return [...paths].sort();
}

self.addEventListener("install", (event) => {
	event.waitUntil(
		(async () => {
			const manifestResponse = await fetch(ASSET_MANIFEST_URL, {
				cache: "no-store",
				credentials: "same-origin",
			});
			if (!manifestResponse.ok) {
				throw new Error("App asset manifest could not be loaded");
			}
			const manifestText = await manifestResponse.text();
			const assetPaths = getHashedAssetPaths(JSON.parse(manifestText));
			const shellResponse = await fetch("/index.html", {
				cache: "no-store",
				credentials: "same-origin",
			});
			if (!shellResponse.ok) throw new Error("App shell could not be loaded");
			const shellHtml = await shellResponse.clone().text();
			const version = hashVersion(
				`${manifestText}\n${shellHtml}\n${assetPaths.join("\n")}`,
			);
			const cacheName = `${CACHE_PREFIX}${version}`;
			const cache = await caches.open(cacheName);
			try {
				await cache.put("/index.html", shellResponse.clone());
				await Promise.all(
					assetPaths.map(async (path) => {
						const response = await fetch(path, {
							cache: "no-store",
							credentials: "same-origin",
						});
						if (!response.ok) {
							throw new Error(`App asset could not be loaded: ${path}`);
						}
						await cache.put(path, response);
					}),
				);
			} catch (error) {
				await caches.delete(cacheName);
				throw error;
			}
		})(),
	);
});

self.addEventListener("message", (event) => {
	if (event.data?.type === "ACTIVATE_UPDATE") void self.skipWaiting();
});

self.addEventListener("activate", (event) => {
	event.waitUntil(
		(async () => {
			const cacheNames = await caches.keys();
			const appShellCaches = cacheNames.filter((name) =>
				name.startsWith(CACHE_PREFIX),
			);
			const currentCache = appShellCaches.at(-1);
			await Promise.all(
				appShellCaches
					.filter((name) => name !== currentCache)
					.map((name) => caches.delete(name)),
			);
			await self.clients.claim();
		})(),
	);
});

self.addEventListener("fetch", (event) => {
	const request = event.request;
	const url = new URL(request.url);
	if (request.method !== "GET" || url.origin !== self.location.origin) return;

	if (request.mode === "navigate") {
		event.respondWith(
			fetch(request).catch(async () => {
				const shell = await caches.match("/index.html");
				if (shell) return shell;
				return Response.error();
			}),
		);
		return;
	}

	if (!HASHED_ASSET.test(url.pathname)) return;
	event.respondWith(
		caches
			.match(request, { ignoreVary: true })
			.then((cached) => cached ?? fetch(request)),
	);
});
