import {
	createResourceRealtimeClient,
	type ResourceRealtimeClient,
} from "@dom/realtime-client";

const REALTIME_URL =
	import.meta.env.VITE_REALTIME_URL ?? "ws://localhost:8765/v1/realtime";
let sharedClient: ResourceRealtimeClient | null = null;

/** Lazily share the single transport across mounted resource features. */
export function getResourceRealtimeClient(): ResourceRealtimeClient {
	sharedClient ??= createResourceRealtimeClient(REALTIME_URL);
	return sharedClient;
}

/** A replaced session cannot reuse its closed socket after the user logs in. */
export function resetResourceRealtimeClient(): void {
	sharedClient?.close();
	sharedClient = null;
}
