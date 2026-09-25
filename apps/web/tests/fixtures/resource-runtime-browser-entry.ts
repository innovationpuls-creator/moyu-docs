import { type ResourceMetadata, ResourceRuntime } from "@dom/resource-runtime";

declare global {
	interface Window {
		createResourceRuntimeForBrowserTest(
			replicaId: string,
			online: boolean,
		): ResourceRuntime;
		resourceMetadataForBrowserTest(resourceId: string): ResourceMetadata;
	}
}

window.resourceMetadataForBrowserTest = (resourceId) => ({
	resourceId,
	projectId: "project-offline-test",
	folderId: null,
	resourceType: "document",
	name: `Resource ${resourceId}`,
	lifecycle: "Active",
	journalSeq: 0,
	snapshot: null,
});

window.createResourceRuntimeForBrowserTest = (replicaId, online) =>
	new ResourceRuntime(
		{
			openResource: async (resourceId) => {
				if (!online) throw new TypeError("Browser is offline");
				return window.resourceMetadataForBrowserTest(resourceId);
			},
		},
		{ replicaId },
	);
