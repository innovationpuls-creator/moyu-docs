import { DomClient } from "@dom/client-sdk";

/** Shared SDK instance. Feature modules use this client through queries or commands. */
export const client = new DomClient();
