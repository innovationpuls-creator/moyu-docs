import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../../shared/api/client";

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
						<strong>待确认的修改</strong>
						<span>{candidate.status}</span>
					</div>
					<p>{candidate.instruction}</p>
					<pre>{JSON.stringify(candidate.operations, null, 2)}</pre>
					<p className="feature-muted" data-testid="ai-changeset-status">
						{applied ? "Applied" : candidate.status}
					</p>
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
