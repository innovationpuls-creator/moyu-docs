import { ResourceRuntime } from "@dom/resource-runtime";
import { client } from "./client";

/** One app-scoped resource lifecycle coordinator and account-isolated cache. */
export const resourceRuntime = new ResourceRuntime({
	openResource: (resourceId) => client.openResource(resourceId),
});
