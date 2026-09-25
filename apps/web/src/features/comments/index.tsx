import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { client } from "../../shared/api/client";
import { ConsoleIcon } from "../../shared/ui/console-icons";
import { formatConsoleDate } from "../../shared/ui/date";

function anchorText(anchor: unknown): string | null {
	if (typeof anchor !== "object" || anchor === null) return null;
	const text = (anchor as Record<string, unknown>).text;
	return typeof text === "string" && text.length > 0 ? text : null;
}

export function CommentsPanel({
	resourceId,
	workspaceId,
	onJumpToAnchor,
}: {
	resourceId: string;
	workspaceId?: string;
	onJumpToAnchor?(text: string): void;
}) {
	const cache = useQueryClient();
	const [body, setBody] = useState("");
	const [threadId, setThreadId] = useState<string | null>(null);
	const [jumpedCommentId, setJumpedCommentId] = useState<string | null>(null);
	const comments = useQuery({
		queryKey: ["comments", resourceId],
		queryFn: () => client.listComments(resourceId),
	});
	const mentionQuery = useMemo(() => {
		const match = body.match(/(?:^|\s)@([^\s@]*)$/);
		return match ? match[1] || "@" : null;
	}, [body]);
	const members = useQuery({
		queryKey: ["member-suggestions", workspaceId, mentionQuery],
		queryFn: () =>
			client.suggestMembers(workspaceId as string, mentionQuery as string),
		enabled: !!workspaceId && mentionQuery !== null,
	});
	const addComment = useMutation({
		mutationFn: () =>
			client.addComment(resourceId, {
				body: body.trim(),
				...(threadId ? { threadId } : {}),
				idempotencyKey: crypto.randomUUID(),
			}),
		onSuccess: async () => {
			setBody("");
			setThreadId(null);
			await cache.invalidateQueries({ queryKey: ["comments", resourceId] });
		},
	});

	function chooseMember(email: string) {
		const at = body.lastIndexOf("@");
		setBody(`${body.slice(0, at)}@${email} `);
	}

	return (
		<section className="drawer-content" aria-label="评论列表">
			<form
				className="comment-composer"
				onSubmit={(event) => {
					event.preventDefault();
					if (body.trim()) addComment.mutate();
				}}
			>
				{threadId && (
					<div className="reply-context">
						正在回复一条评论
						<button type="button" onClick={() => setThreadId(null)}>
							取消回复
						</button>
					</div>
				)}
				<textarea
					value={body}
					onChange={(event) => setBody(event.target.value)}
					placeholder="写下评论…"
					aria-label="评论内容"
					data-testid="comment-input"
				/>
				{mentionQuery !== null && (
					<div className="mention-options" role="listbox" aria-label="成员建议">
						{members.data?.suggestions.map((member) => (
							<button
								key={member.accountId}
								type="button"
								role="option"
								data-testid="mention-option"
								onClick={() => chooseMember(member.email)}
							>
								{member.email}
							</button>
						))}
					</div>
				)}
				<button
					type="submit"
					data-testid="comment-submit"
					disabled={!body.trim() || addComment.isPending}
				>
					{addComment.isPending ? "发送中…" : "发送评论"}
				</button>
			</form>
			{addComment.isError && (
				<p className="feature-error" role="alert">
					评论发送失败，请重试。
				</p>
			)}
			{comments.isLoading && <p className="feature-muted">正在载入评论…</p>}
			{comments.isError && (
				<p className="feature-error" role="alert">
					评论暂时不可用。
				</p>
			)}
			{comments.data?.items.map((item) => {
				const quote = anchorText(item.anchor);
				return (
					<article
						className="comment-card"
						key={item.commentId}
						data-testid="comment-row"
						data-jumped={
							jumpedCommentId === item.commentId ? "true" : undefined
						}
					>
						<div className="comment-card-meta">
							<span>
								<ConsoleIcon name="comments" size={14} /> 评论
							</span>
							<time dateTime={item.createdAt}>
								{formatConsoleDate(item.createdAt)}
							</time>
						</div>
						<p>{item.body}</p>
						{quote && (
							<button
								type="button"
								className="comment-anchor"
								data-testid="comment-anchor"
								onClick={() => {
									setJumpedCommentId(item.commentId);
									onJumpToAnchor?.(quote);
								}}
							>
								引用：{quote}
							</button>
						)}
						<button
							type="button"
							className="comment-reply"
							onClick={() => setThreadId(item.threadId)}
						>
							回复
						</button>
					</article>
				);
			})}
			{comments.data?.items.length === 0 && (
				<p className="feature-muted">还没有评论。</p>
			)}
		</section>
	);
}
