import { createHash } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import * as Y from "yjs";

const MAX_CURRENT_UPDATE_BYTES = 32 * 1024 * 1024;
const MAX_CONTENT_NODES = 100_000;
const LEGACY_TEXT_ROOT = "content";
const YJS_ROOT = "prosemirror";

export interface ResourceContentSnapshot {
	text: string;
	nodes: ContentNode[];
}

export interface ResourceContentReadRequest {
	resourceId: string;
	atJournalSeq?: number;
}

export interface ResourceContentReplaceRequest {
	resourceId: string;
	operationId: string;
	expectedJournalSeq?: number;
	createdBy: string | null;
	reason: "import" | "history-restore" | "ai-changeset";
	restoreTargetSeq?: number;
	snapshot: ResourceContentSnapshot;
}

export interface ResourceContentMutationReceipt {
	journalSeq: number;
	broadcastJournalSeq: number;
	update: Uint8Array;
}

export class ResourceContentError extends Error {
	constructor(
		readonly code: string,
		message: string,
		readonly nextJournalSeq?: number,
	) {
		super(message);
	}
}

interface MaterializedState {
	doc: Y.Doc;
	snapshot: ResourceContentSnapshot;
	stateSeq: number;
	maxSeq: number;
}

interface JournalRow {
	journal_seq: string | number;
	update_bytes: Buffer;
	update_hash: string;
	mutation_kind: string | null;
}

interface CheckpointRow {
	base_journal_seq: string | number;
	snapshot: unknown;
}

interface MutationRow {
	journal_seq: string | number;
	mutation_request_hash: string;
}

export class PostgresResourceContentService {
	constructor(private readonly pool: Pick<Pool, "connect">) {}

	async read(request: ResourceContentReadRequest): Promise<{
		resourceId: string;
		journalSeq: number;
		snapshot: ResourceContentSnapshot;
	}> {
		const client = await this.pool.connect();
		let transactionOpen = false;
		try {
			await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
			transactionOpen = true;
			const state = await this.materialize(
				client,
				request.resourceId,
				request.atJournalSeq,
			);
			const journalSeq = request.atJournalSeq ?? state.maxSeq;
			const result = {
				resourceId: request.resourceId,
				journalSeq,
				snapshot: state.snapshot,
			};
			state.doc.destroy();
			await client.query("COMMIT");
			transactionOpen = false;
			return result;
		} catch (error) {
			if (transactionOpen) await client.query("ROLLBACK");
			throw error;
		} finally {
			client.release();
		}
	}

	async readCurrentState(resourceId: string): Promise<Uint8Array> {
		const client = await this.pool.connect();
		let transactionOpen = false;
		try {
			await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
			transactionOpen = true;
			const state = await this.materialize(client, resourceId);
			const update = Y.encodeStateAsUpdate(state.doc);
			state.doc.destroy();
			await client.query("COMMIT");
			transactionOpen = false;
			return update;
		} catch (error) {
			if (transactionOpen) await client.query("ROLLBACK");
			throw error;
		} finally {
			client.release();
		}
	}

	async replace(
		request: ResourceContentReplaceRequest,
	): Promise<ResourceContentMutationReceipt> {
		const snapshot = normalizeSnapshot(request.snapshot);
		const requestHash = createHash("sha256")
			.update(
				canonicalJson({
					resourceId: request.resourceId,
					createdBy: request.createdBy,
					reason: request.reason,
					restoreTargetSeq: request.restoreTargetSeq ?? null,
					expectedJournalSeq: request.expectedJournalSeq ?? null,
					snapshot,
				}),
			)
			.digest("hex");
		const client = await this.pool.connect();
		let transactionOpen = false;
		let receipt: ResourceContentMutationReceipt;
		try {
			await client.query("BEGIN");
			transactionOpen = true;
			await client.query(
				"SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
				[request.resourceId],
			);
			await this.assertResourceActive(client, request.resourceId);
			const currentSeq = await this.maxSeq(client, request.resourceId);
			const existing = await client.query<MutationRow>(
				"SELECT journal_seq, mutation_request_hash " +
					"FROM collab.resource_update_journal " +
					"WHERE resource_id=$1::uuid AND operation_id=$2::uuid LIMIT 1",
				[request.resourceId, request.operationId],
			);
			if (existing.rows[0]) {
				if (existing.rows[0].mutation_request_hash !== requestHash) {
					throw new ResourceContentError(
						"IDEMPOTENCY_KEY_CONFLICT",
						"operation identity was already used for different content",
					);
				}
				const state = await this.materialize(client, request.resourceId);
				receipt = {
					journalSeq: Number(existing.rows[0].journal_seq),
					broadcastJournalSeq: state.maxSeq,
					update: Y.encodeStateAsUpdate(state.doc),
				};
				state.doc.destroy();
			} else {
				if (
					request.expectedJournalSeq !== undefined &&
					request.expectedJournalSeq !== currentSeq
				) {
					throw new ResourceContentError(
						"RESOURCE_JOURNAL_SEQUENCE_CONFLICT",
						"Resource content changed after this operation was prepared",
						currentSeq + 1,
					);
				}
				const state = await this.materialize(client, request.resourceId);
				replaceFragment(state.doc, snapshot.nodes);
				const update = Y.encodeStateAsUpdate(state.doc);
				if (update.byteLength > MAX_CURRENT_UPDATE_BYTES) {
					state.doc.destroy();
					throw new ResourceContentError(
						"RESOURCE_CONTENT_UNAVAILABLE",
						"resulting Yjs state exceeds the Realtime limit",
					);
				}
				const journalSeq = currentSeq + 1;
				const updateHash = createHash("sha256").update(update).digest("hex");
				await client.query(
					"INSERT INTO collab.resource_update_journal " +
						"(resource_id,journal_seq,ownership_epoch,update_bytes,update_hash," +
						"durable_at,operation_id,mutation_request_hash,mutation_kind," +
						"restore_target_seq) VALUES ($1::uuid,$2,1,$3,$4,now(),$5::uuid," +
						"$6,$7,$8)",
					[
						request.resourceId,
						journalSeq,
						Buffer.from(update),
						updateHash,
						request.operationId,
						requestHash,
						request.reason,
						request.restoreTargetSeq ?? null,
					],
				);
				await client.query(
					"INSERT INTO collab.resource_checkpoints " +
						"(resource_id,checkpoint_seq,base_journal_seq,snapshot,created_by) " +
						"SELECT $1::uuid,COALESCE(MAX(checkpoint_seq),0)+1,$2,$3::jsonb," +
						"$4::uuid FROM collab.resource_checkpoints " +
						"WHERE resource_id=$1::uuid",
					[
						request.resourceId,
						journalSeq,
						JSON.stringify(snapshot),
						request.createdBy,
					],
				);
				receipt = {
					journalSeq,
					broadcastJournalSeq: journalSeq,
					update,
				};
				state.doc.destroy();
			}
			await client.query("COMMIT");
			transactionOpen = false;
		} catch (error) {
			if (transactionOpen) await client.query("ROLLBACK");
			throw error;
		} finally {
			client.release();
		}
		return receipt;
	}

	private async materialize(
		client: PoolClient,
		resourceId: string,
		atJournalSeq?: number,
	): Promise<MaterializedState> {
		await this.assertResourceActive(client, resourceId);
		const maxSeq = await this.maxSeq(client, resourceId);
		const targetSeq = atJournalSeq ?? maxSeq;
		if (targetSeq > maxSeq) {
			throw new ResourceContentError(
				"RESOURCE_NOT_FOUND",
				"Journal version not found",
			);
		}

		let journalState: { doc: Y.Doc; seq: number } | null = null;
		let upperSeq = targetSeq;
		let sawLegacyEntry = false;
		while (true) {
			const rows = await client.query<JournalRow>(
				"SELECT journal_seq,update_bytes,update_hash,mutation_kind " +
					"FROM collab.resource_update_journal WHERE resource_id=$1::uuid " +
					"AND journal_seq<=$2 AND durable_at IS NOT NULL " +
					"ORDER BY journal_seq DESC LIMIT 32",
				[resourceId, upperSeq],
			);
			if (rows.rows.length === 0) break;
			for (const row of rows.rows) {
				const seq = Number(row.journal_seq);
				const bytes = new Uint8Array(row.update_bytes);
				if (bytes.byteLength > MAX_CURRENT_UPDATE_BYTES) {
					throw new ResourceContentError(
						"RESOURCE_CONTENT_UNAVAILABLE",
						"durable Yjs state exceeds the Realtime limit",
					);
				}
				if (isLegacyMarker(bytes)) {
					sawLegacyEntry = true;
					continue;
				}
				const digest = createHash("sha256").update(bytes).digest("hex");
				if (digest !== row.update_hash) {
					throw new ResourceContentError(
						"RESOURCE_CONTENT_UNAVAILABLE",
						"durable Journal update failed hash verification",
					);
				}
				const doc = new Y.Doc();
				try {
					Y.applyUpdate(doc, bytes);
					assertUpdateWasComplete(bytes, doc);
					migrateLegacyText(doc);
					journalState = { doc, seq };
					break;
				} catch (error) {
					doc.destroy();
					if (error instanceof ResourceContentError) throw error;
					throw new ResourceContentError(
						"RESOURCE_CONTENT_UNAVAILABLE",
						"durable Journal entry is not a complete Yjs state",
					);
				}
			}
			if (journalState) break;
			upperSeq = Number(rows.rows[rows.rows.length - 1].journal_seq) - 1;
			if (upperSeq < 1) break;
		}

		let checkpointState: { doc: Y.Doc; seq: number } | null = null;
		let beforeCheckpointSeq = targetSeq + 1;
		while (true) {
			const rows = await client.query<CheckpointRow>(
				"SELECT base_journal_seq,snapshot FROM collab.resource_checkpoints " +
					"WHERE resource_id=$1::uuid AND base_journal_seq<$2 " +
					"ORDER BY base_journal_seq DESC,checkpoint_seq DESC LIMIT 32",
				[resourceId, beforeCheckpointSeq],
			);
			if (rows.rows.length === 0) break;
			for (const row of rows.rows) {
				try {
					const snapshot = normalizeSnapshot(row.snapshot);
					checkpointState = {
						doc: docFromNodes(snapshot.nodes),
						seq: Number(row.base_journal_seq),
					};
					break;
				} catch {
					// Older checkpoint metadata did not contain a content projection.
				}
			}
			if (checkpointState) break;
			beforeCheckpointSeq = Number(
				rows.rows[rows.rows.length - 1].base_journal_seq,
			);
		}

		let selected: { doc: Y.Doc; seq: number } | null = journalState;
		if (checkpointState && (!selected || checkpointState.seq > selected.seq)) {
			selected?.doc.destroy();
			selected = checkpointState;
		} else {
			checkpointState?.doc.destroy();
		}
		if (selected === null) {
			if (maxSeq > 0 || sawLegacyEntry) {
				throw new ResourceContentError(
					"RESOURCE_CONTENT_UNAVAILABLE",
					"no valid Yjs state or semantic checkpoint exists for this Resource",
				);
			}
			selected = { doc: docFromNodes([]), seq: 0 };
		}
		if (sawLegacyEntry && selected.seq < targetSeq) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"legacy Journal entries after the available content checkpoint cannot be reconstructed",
			);
		}
		return {
			doc: selected.doc,
			snapshot: snapshotFromDoc(selected.doc),
			stateSeq: selected.seq,
			maxSeq,
		};
	}

	private async maxSeq(
		client: PoolClient,
		resourceId: string,
	): Promise<number> {
		const result = await client.query<{ max_seq: string | number }>(
			"SELECT COALESCE(MAX(journal_seq),0) AS max_seq " +
				"FROM collab.resource_update_journal " +
				"WHERE resource_id=$1::uuid AND durable_at IS NOT NULL",
			[resourceId],
		);
		return Number(result.rows[0]?.max_seq ?? 0);
	}

	private async assertResourceActive(
		client: PoolClient,
		resourceId: string,
	): Promise<void> {
		const result = await client.query<{ lifecycle: string }>(
			"SELECT lifecycle FROM core.resources WHERE resource_id=$1::uuid",
			[resourceId],
		);
		if (result.rows[0]?.lifecycle !== "Active") {
			throw new ResourceContentError(
				"RESOURCE_NOT_FOUND",
				"Resource not found",
			);
		}
	}
}

export function snapshotFromDoc(doc: Y.Doc): ResourceContentSnapshot {
	const fragment = doc.getXmlFragment(YJS_ROOT);
	const nodes = fragment.toArray().map((item) => {
		if (!(item instanceof Y.XmlElement)) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"Yjs document has a non-block ProseMirror root node",
			);
		}
		return nodeFromXml(item);
	});
	if (nodes.length === 0) nodes.push({ kind: "paragraph", children: [] });
	return { nodes, text: contentNodesToText(nodes) };
}

export function docFromNodes(nodes: ContentNode[]): Y.Doc {
	const doc = new Y.Doc();
	const fragment = doc.getXmlFragment(YJS_ROOT);
	const canonicalNodes = normalizeNodes(nodes);
	fragment.insert(0, canonicalNodes.map(nodeToXml));
	return doc;
}

export function replaceFragment(doc: Y.Doc, nodes: ContentNode[]): void {
	const fragment = doc.getXmlFragment(YJS_ROOT);
	const canonicalNodes = normalizeNodes(nodes);
	doc.transact(() => {
		if (fragment.length > 0) fragment.delete(0, fragment.length);
		fragment.insert(0, canonicalNodes.map(nodeToXml));
	}, "resource-content-mutation");
}

function normalizeSnapshot(value: unknown): ResourceContentSnapshot {
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new ResourceContentError(
			"RESOURCE_CONTENT_UNAVAILABLE",
			"content snapshot must be an object",
		);
	}
	const candidate = value as { text?: unknown; nodes?: unknown };
	let nodes: ContentNode[];
	if (Array.isArray(candidate.nodes)) {
		nodes = normalizeNodes(candidate.nodes as ContentNode[]);
	} else if (typeof candidate.text === "string") {
		nodes = textToNodes(candidate.text);
	} else {
		throw new ResourceContentError(
			"RESOURCE_CONTENT_UNAVAILABLE",
			"content snapshot must include nodes or text",
		);
	}
	if (
		nodes.length === 0 &&
		typeof candidate.text === "string" &&
		candidate.text.length > 0
	) {
		nodes = textToNodes(candidate.text);
	}
	return { nodes, text: contentNodesToText(nodes) };
}

function normalizeNodes(nodes: ContentNode[]): ContentNode[] {
	if (nodes.length > MAX_CONTENT_NODES) {
		throw new ResourceContentError(
			"RESOURCE_CONTENT_UNAVAILABLE",
			"content snapshot contains too many nodes",
		);
	}
	const normalized = nodes.map((node) => validateNode(node));
	const blocks = normalized.flatMap((node) =>
		node.kind === "text"
			? [{ kind: "paragraph", children: [node] } satisfies ContentNode]
			: [node],
	);
	return blocks.length > 0 ? blocks : [{ kind: "paragraph", children: [] }];
}

function validateNode(node: ContentNode): ContentNode {
	if (!node || typeof node !== "object" || typeof node.kind !== "string") {
		throw new ResourceContentError(
			"RESOURCE_CONTENT_UNAVAILABLE",
			"invalid content node",
		);
	}
	switch (node.kind) {
		case "text": {
			if (typeof node.text !== "string") throw invalidNode("text node");
			const marks = node.marks ?? [];
			if (marks.some((mark) => !["bold", "italic", "code"].includes(mark))) {
				throw invalidNode("text marks");
			}
			return {
				kind: "text",
				text: node.text,
				...(marks.length ? { marks } : {}),
			};
		}
		case "paragraph":
			return {
				kind: "paragraph",
				children: validateTextChildren(node.children ?? []),
			};
		case "heading":
			if (![1, 2, 3].includes(node.level)) throw invalidNode("heading level");
			return {
				kind: "heading",
				level: node.level,
				children: validateTextChildren(node.children ?? []),
			};
		case "list":
			return {
				kind: "list",
				...(node.ordered === undefined ? {} : { ordered: node.ordered }),
				children: (node.children ?? []).map((child) => {
					if (child.kind !== "paragraph") throw invalidNode("list item");
					return {
						kind: "paragraph",
						children: validateTextChildren(child.children ?? []),
					};
				}),
			};
		case "image":
		case "attachment":
			if (
				typeof node.nodeId !== "string" ||
				node.nodeId.length === 0 ||
				typeof node.assetId !== "string" ||
				node.assetId.length === 0 ||
				typeof node.label !== "string"
			) {
				throw invalidNode("asset reference");
			}
			return {
				kind: node.kind,
				nodeId: node.nodeId,
				assetId: node.assetId,
				label: node.label,
			};
		default:
			throw invalidNode("node kind");
	}
}

function validateTextChildren(nodes: ContentNode[]): TextNode[] {
	return nodes.map((node) => {
		if (node.kind !== "text") throw invalidNode("paragraph child");
		return validateNode(node) as TextNode;
	});
}

function textToNodes(text: string): ContentNode[] {
	return text.split("\n").map((line) => ({
		kind: "paragraph",
		children: line ? [{ kind: "text", text: line }] : [],
	}));
}

function contentNodesToText(nodes: ContentNode[]): string {
	return nodes
		.map((node) => {
			switch (node.kind) {
				case "text":
					return node.text;
				case "paragraph":
				case "heading":
					return (node.children ?? []).map((child) => child.text).join("");
				case "list":
					return (node.children ?? [])
						.map((paragraph) =>
							(paragraph.children ?? []).map((child) => child.text).join(""),
						)
						.join("\n");
				case "image":
					return `![${encodeTokenPart(node.label, true)}](asset://${encodeTokenPart(node.assetId, false)})`;
				case "attachment":
					return `[${encodeTokenPart(node.label, true)}](asset://${encodeTokenPart(node.assetId, false)})`;
				default:
					throw invalidNode("content projection node kind");
			}
		})
		.join("\n");
}

function encodeTokenPart(value: string, readableSpaces: boolean): string {
	const encoded = encodeURIComponent(value).replace(
		/[!'()*]/gu,
		(character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
	);
	return readableSpaces ? encoded.replaceAll("%20", " ") : encoded;
}

function nodeToXml(node: ContentNode): Y.XmlElement {
	switch (node.kind) {
		case "text":
			throw invalidNode("root text node");
		case "image":
		case "attachment": {
			const element = new Y.XmlElement(node.kind);
			element.setAttribute("nodeId", node.nodeId);
			element.setAttribute("assetId", node.assetId);
			element.setAttribute("label", node.label);
			return element;
		}
		case "paragraph":
		case "heading": {
			const element = new Y.XmlElement(node.kind);
			if (node.kind === "heading") {
				element.setAttribute("level", String(node.level));
			}
			const children = (node.children ?? []).map(textToXml);
			if (children.length > 0) element.insert(0, children);
			return element;
		}
		case "list": {
			const list = new Y.XmlElement(
				node.ordered ? "orderedList" : "bulletList",
			);
			const items = (node.children ?? []).map((paragraph) => {
				const item = new Y.XmlElement("listItem");
				item.insert(0, [nodeToXml(paragraph)]);
				return item;
			});
			if (items.length > 0) list.insert(0, items);
			return list;
		}
		default:
			throw invalidNode("content node kind");
	}
}

function textToXml(node: TextNode): Y.XmlText {
	const text = new Y.XmlText();
	if (node.text.length > 0) {
		const attributes: Record<string, Record<string, never>> = {};
		for (const mark of node.marks ?? []) {
			attributes[
				mark === "bold" ? "strong" : mark === "italic" ? "em" : "code"
			] = {};
		}
		text.insert(
			0,
			node.text,
			Object.keys(attributes).length ? attributes : undefined,
		);
	}
	return text;
}

function nodeFromXml(element: Y.XmlElement): ContentNode {
	if (element.nodeName === "paragraph") {
		return { kind: "paragraph", children: readTextChildren(element) };
	}
	if (element.nodeName === "heading") {
		const level = Number(element.getAttribute("level") ?? 1);
		if (![1, 2, 3].includes(level)) throw invalidNode("Yjs heading level");
		return {
			kind: "heading",
			level: level as 1 | 2 | 3,
			children: readTextChildren(element),
		};
	}
	if (element.nodeName === "bulletList" || element.nodeName === "orderedList") {
		return {
			kind: "list",
			...(element.nodeName === "orderedList" ? { ordered: true } : {}),
			children: element.toArray().map((item) => {
				if (!(item instanceof Y.XmlElement) || item.nodeName !== "listItem") {
					throw invalidNode("Yjs list item");
				}
				const children = item.toArray();
				if (
					children.length !== 1 ||
					!(children[0] instanceof Y.XmlElement) ||
					children[0].nodeName !== "paragraph"
				) {
					throw invalidNode("Yjs list paragraph");
				}
				return {
					kind: "paragraph",
					children: readTextChildren(children[0]),
				};
			}),
		};
	}
	if (element.nodeName === "image" || element.nodeName === "attachment") {
		const attrs = element.getAttributes();
		return validateNode({
			kind: element.nodeName,
			nodeId: String(attrs.nodeId ?? ""),
			assetId: String(attrs.assetId ?? ""),
			label: String(attrs.label ?? ""),
		});
	}
	throw invalidNode(`Yjs element ${element.nodeName}`);
}

function readTextChildren(element: Y.XmlElement): TextNode[] {
	return element.toArray().flatMap((child) => {
		if (!(child instanceof Y.XmlText)) throw invalidNode("Yjs inline node");
		const parts: TextNode[] = [];
		for (const delta of child.toDelta()) {
			if (typeof delta.insert !== "string") throw invalidNode("Yjs text embed");
			const attributes = delta.attributes ?? {};
			const marks = Object.keys(attributes).flatMap((mark) => {
				if (mark === "strong") return ["bold" as const];
				if (mark === "em") return ["italic" as const];
				if (mark === "code") return ["code" as const];
				throw invalidNode(`Yjs text mark ${mark}`);
			});
			parts.push({
				kind: "text",
				text: delta.insert,
				...(marks.length > 0 ? { marks } : {}),
			});
		}
		return parts;
	});
}

function migrateLegacyText(doc: Y.Doc): void {
	const fragment = doc.getXmlFragment(YJS_ROOT);
	if (fragment.length > 0) return;
	const legacyText = doc.getText(LEGACY_TEXT_ROOT).toString();
	const nodes = textToNodes(legacyText);
	fragment.insert(0, nodes.map(nodeToXml));
}

function assertUpdateWasComplete(update: Uint8Array, doc: Y.Doc): void {
	const decoded = Y.decodeUpdate(update);
	const stateVector = Y.decodeStateVector(Y.encodeStateVector(doc));
	for (const struct of decoded.structs) {
		const expectedClock = struct.id.clock + struct.length;
		if ((stateVector.get(struct.id.client) ?? 0) < expectedClock) {
			throw new ResourceContentError(
				"RESOURCE_CONTENT_UNAVAILABLE",
				"Journal entry is not a complete Yjs state",
			);
		}
	}
}

function isLegacyMarker(bytes: Uint8Array): boolean {
	const prefix = Buffer.from(bytes.subarray(0, 32))
		.toString("utf8")
		.trimStart();
	return prefix.startsWith("{") || prefix.startsWith("restore@");
}

function canonicalJson(value: unknown): string {
	if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
	if (typeof value === "object" && value !== null) {
		const entries = Object.entries(value as Record<string, unknown>).sort(
			([a], [b]) => a.localeCompare(b),
		);
		return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
	}
	return JSON.stringify(value);
}

function invalidNode(reason: string): ResourceContentError {
	return new ResourceContentError(
		"RESOURCE_CONTENT_UNAVAILABLE",
		`invalid Resource content: ${reason}`,
	);
}

interface TextNode {
	kind: "text";
	text: string;
	marks?: Array<"bold" | "italic" | "code">;
}

type ContentNode =
	| TextNode
	| { kind: "paragraph"; children?: TextNode[] }
	| { kind: "heading"; level: 1 | 2 | 3; children?: TextNode[] }
	| {
			kind: "list";
			ordered?: boolean;
			children?: Array<{ kind: "paragraph"; children?: TextNode[] }>;
	  }
	| {
			kind: "image" | "attachment";
			nodeId: string;
			assetId: string;
			label: string;
	  };
