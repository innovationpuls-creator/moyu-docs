import type { Pool } from "pg";
import { PostgresResourceContentService } from "./resource_content.js";

export interface CurrentResourceStateProvider {
	readCurrentState(resourceId: string): Promise<Uint8Array | null>;
}

/** Durable Yjs state reads share Realtime's Resource content materializer. */
export class PostgresCurrentResourceStateProvider
	implements CurrentResourceStateProvider
{
	private readonly content: PostgresResourceContentService;

	constructor(pool: Pick<Pool, "connect">) {
		this.content = new PostgresResourceContentService(pool);
	}

	readCurrentState(resourceId: string): Promise<Uint8Array> {
		return this.content.readCurrentState(resourceId);
	}
}
