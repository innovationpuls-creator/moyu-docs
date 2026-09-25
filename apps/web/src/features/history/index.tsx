import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client } from "../../shared/api/client";
import { formatConsoleDate } from "../../shared/ui/date";

function historyKindLabel(kind: string): string {
	if (kind === "NamedVersion") return "命名版本";
	if (kind === "Restore") return "恢复记录";
	return "检查点";
}

export function HistoryPanel({
	resourceId,
	journalSeq,
	onRestored,
}: {
	resourceId: string;
	journalSeq: number;
	onRestored?(newSeq: number): Promise<void>;
}) {
	const cache = useQueryClient();
	const [label, setLabel] = useState("");
	const history = useQuery({
		queryKey: ["history", resourceId],
		queryFn: () => client.listHistory(resourceId),
	});
	const saveVersion = useMutation({
		mutationFn: () =>
			client.createNamedVersion(resourceId, label.trim(), journalSeq),
		onSuccess: async () => {
			setLabel("");
			await cache.invalidateQueries({ queryKey: ["history", resourceId] });
		},
	});
	const restoreVersion = useMutation({
		mutationFn: (baseJournalSeq: number) =>
			client.restoreVersion(resourceId, baseJournalSeq),
		onSuccess: async (result) => {
			await cache.invalidateQueries({ queryKey: ["history", resourceId] });
			await onRestored?.(result.newSeq);
		},
	});

	return (
		<section className="drawer-content" aria-label="文档历史">
			<form
				className="version-composer"
				onSubmit={(event) => {
					event.preventDefault();
					if (label.trim() && journalSeq > 0) saveVersion.mutate();
				}}
			>
				<input
					value={label}
					onChange={(event) => setLabel(event.target.value)}
					placeholder="为当前版本命名"
					aria-label="版本名称"
				/>
				<button
					type="submit"
					disabled={!label.trim() || journalSeq < 1 || saveVersion.isPending}
				>
					保存版本
				</button>
			</form>
			{history.isLoading && <p className="feature-muted">正在载入历史…</p>}
			{history.isError && (
				<p className="feature-error" role="alert">
					历史记录暂时不可用。
				</p>
			)}
			{saveVersion.isError && (
				<p className="feature-error" role="alert">
					版本创建失败，请重试。
				</p>
			)}
			{restoreVersion.isError && (
				<p className="feature-error" role="alert">
					版本恢复失败，请重试。
				</p>
			)}
			{history.data?.items.map((item) => (
				<article className="history-card" key={`${item.seq}-${item.kind}`}>
					<div className="history-card-copy">
						<div className="history-card-title">
							<strong>{item.label ?? historyKindLabel(item.kind)}</strong>
							<span className="history-sequence">
								{item.seq === journalSeq ? "当前" : `#${item.seq}`}
							</span>
						</div>
						<small>{formatConsoleDate(item.occurredAt)}</small>
					</div>
					<button
						type="button"
						className="history-restore-button"
						disabled={restoreVersion.isPending || item.seq < 1}
						onClick={() => restoreVersion.mutate(item.seq)}
					>
						恢复到此版本
					</button>
				</article>
			))}
			{history.data?.items.length === 0 && (
				<p className="feature-muted">还没有版本记录。</p>
			)}
		</section>
	);
}
