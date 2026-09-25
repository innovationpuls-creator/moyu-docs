import {
	createPublicShareRealtimeClient,
	createResourceRealtimeClient,
	type ResourceRealtimeClient,
} from "@dom/realtime-client";

const defaultRealtimeUrl = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.hostname}:8765/v1/realtime`;
const REALTIME_URL = import.meta.env.VITE_REALTIME_URL ?? defaultRealtimeUrl;
const publicShareRealtimeUrl = new URL(REALTIME_URL);
publicShareRealtimeUrl.pathname = "/public-share";
publicShareRealtimeUrl.search = "";
publicShareRealtimeUrl.hash = "";
let sharedClient: ResourceRealtimeClient | null = null;

/** Lazily share the single transport across mounted resource features. */
export function getResourceRealtimeClient(): ResourceRealtimeClient {
	sharedClient ??= createResourceRealtimeClient(REALTIME_URL);
	return sharedClient;
}

/** A public share uses its own socket and anonymous token authentication. */
export function createPublicShareClient(token: string): ResourceRealtimeClient {
	return createPublicShareRealtimeClient(
		publicShareRealtimeUrl.toString(),
		token,
	);
}

/** A replaced session cannot reuse its closed socket after the user logs in. */
export function resetResourceRealtimeClient(): void {
	sharedClient?.close();
	sharedClient = null;
}
