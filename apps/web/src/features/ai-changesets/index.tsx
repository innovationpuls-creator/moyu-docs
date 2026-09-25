import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../../shared/api/client";

function operationPreview(operation: unknown): {
	label: string;
	content: string | null;
} {
	if (typeof operation !== "object" || operation === null) {
		return { label: "内容调整", content: null };
	}
	const value = (operation as Record<string, unknown>).value;
	const op = (operation as Record<string, unknown>).op;
	return {
		label: op === "summary-insert" ? "新增内容" : "内容调整",
		content: typeof value === "string" ? value : null,
	};
}

function operationKey(operation: unknown, counts: Map<string, number>): string {
	const signature = JSON.stringify(operation) ?? String(operation);
	const occurrence = counts.get(signature) ?? 0;
	counts.set(signature, occurrence + 1);
	return `${signature}-${occurrence}`;
}

export function AiChangesetsPanel({
	resourceId,
	onApplied,
}: {
	resourceId: string;
	onApplied?(): Promise<void>;
}) {
	const cache = useQueryClient();
	const [instruction, setInstruction] = useState("");
	const [pendingId, setPendingId] = useState<string | null>(null);
	const [applied, setApplied] = useState(false);
	const proposal = useMutation({
		mutationFn: () => client.proposeChangeSet(resourceId, instruction.trim()),
		onSuccess: (result) => {
			setPendingId(result.changesetId);
			setApplied(false);
		},
	});
	const apply = useMutation({
		mutationFn: (changesetId: string) => client.applyChangeSet(changesetId),
		onSuccess: async () => {
			setApplied(true);
			await cache.invalidateQueries({ queryKey: ["history", resourceId] });
			await onApplied?.();
		},
	});
	const candidate = proposal.data;
	const operationKeyCounts = new Map<string, number>();

	return (
		<section className="drawer-content" aria-label="AI 文档修改">
			<form
				className="ai-composer"
				onSubmit={(event) => {
					event.preventDefault();
					if (instruction.trim()) proposal.mutate();
				}}
			>
				<label htmlFor="ai-instruction">描述你希望 AI 修改的内容</label>
				<p className="ai-composer-hint">
					修改会先作为提议展示，确认后才会写入文档。
				</p>
				<textarea
					id="ai-instruction"
					data-testid="ai-instruction"
					value={instruction}
					onChange={(event) => setInstruction(event.target.value)}
					placeholder="例如：把这段内容整理成三条要点"
				/>
				<button
					type="submit"
					data-testid="ai-propose"
					disabled={!instruction.trim() || proposal.isPending}
				>
					{proposal.isPending ? "正在生成提议…" : "生成修改提议"}
				</button>
			</form>
			{proposal.isError && (
				<p className="feature-error" role="alert">
					提议生成失败，请重试。
				</p>
			)}
			{apply.isError && (
				<p className="feature-error" role="alert">
					应用失败，提议仍可再次应用。
				</p>
			)}
			{candidate && pendingId && (
				<article className="changeset-card" data-testid="ai-pending-changeset">
					<div className="changeset-card-heading">
						<div>
							<span className="changeset-overline">修改提议</span>
							<strong>待确认的修改</strong>
						</div>
						<span
							className={`changeset-status-badge ${applied ? "applied" : ""}`}
						>
							{applied ? "已应用" : "待确认"}
						</span>
					</div>
					<p>{candidate.instruction}</p>
					<div className="changeset-operation-heading">
						<strong>提议内容</strong>
						<span>{candidate.operations.length} 项调整</span>
					</div>
					{candidate.operations.length > 0 ? (
						<ul className="changeset-operation-list">
							{candidate.operations.map((operation, index) => {
								const preview = operationPreview(operation);
								return (
									<li
										key={`${pendingId}-${operationKey(operation, operationKeyCounts)}`}
									>
										<span className="changeset-operation-index">
											{index + 1}
										</span>
										<div>
											<strong>{preview.label}</strong>
											{preview.content && <p>{preview.content}</p>}
										</div>
									</li>
								);
							})}
						</ul>
					) : (
						<p className="changeset-empty-preview">
							这份提议没有可预览的调整。
						</p>
					)}
					<span className="sr-only" data-testid="ai-changeset-status">
						{applied ? "Applied" : candidate.status}
					</span>
					<button
						type="button"
						data-testid="ai-apply"
						disabled={apply.isPending || applied}
						onClick={() => apply.mutate(pendingId)}
					>
						{apply.isPending ? "正在应用…" : applied ? "已应用" : "应用此修改"}
					</button>
				</article>
			)}
		</section>
	);
}
