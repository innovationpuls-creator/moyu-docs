import type {
	ReopenCommentThreadResponse,
	ResolveCommentThreadResponse,
} from "@dom/client-sdk";
import { DomApiError } from "@dom/client-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { client } from "../../shared/api/client";
import { getResourceRealtimeClient } from "../../shared/realtime";

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
	const account = useQuery({
		queryKey: ["account"],
		queryFn: () => client.me(),
	});
	const [body, setBody] = useState("");
	const [threadId, setThreadId] = useState<string | null>(null);
	const [jumpedCommentId, setJumpedCommentId] = useState<string | null>(null);
	const [statusError, setStatusError] = useState("");
	const comments = useQuery({
		queryKey: ["comments", resourceId],
		queryFn: () => client.listComments(resourceId),
		refetchInterval: 4000,
	});
	useEffect(
		() =>
			getResourceRealtimeClient().onResourceEvent(resourceId, () => {
				void cache.invalidateQueries({ queryKey: ["comments", resourceId] });
			}),
		[cache, resourceId],
	);
	const capabilities = useQuery({
		queryKey: ["resource-capabilities", resourceId],
		queryFn: () => client.getResourceCapabilities(resourceId),
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
			setStatusError("");
			await cache.invalidateQueries({ queryKey: ["comments", resourceId] });
		},
		onError: async (error) => {
			if (
				error instanceof DomApiError &&
				error.errorCode === "COMMENT_THREAD_RESOLVED"
			) {
				setStatusError("这条讨论已关闭，请先重新打开后再回复。");
				await cache.invalidateQueries({ queryKey: ["comments", resourceId] });
				return;
			}
			setStatusError("");
		},
	});
	const changeThreadStatus = useMutation<
		ResolveCommentThreadResponse | ReopenCommentThreadResponse,
		Error,
		{ id: string; action: "resolve" | "reopen" }
	>({
		mutationFn: ({
			id,
			action,
		}: {
			id: string;
			action: "resolve" | "reopen";
		}) =>
			action === "resolve"
				? client.resolveCommentThread(resourceId, id)
				: client.reopenCommentThread(resourceId, id),
		onSuccess: async () => {
			setStatusError("");
			await cache.invalidateQueries({ queryKey: ["comments", resourceId] });
		},
		onError: () => setStatusError("讨论状态更新失败，请检查权限后重试。"),
	});

	function chooseMember(email: string) {
		const at = body.lastIndexOf("@");
		setBody(`${body.slice(0, at)}@${email} `);
	}

	const commentItems = comments.data?.items ?? [];
	const selectedThread = commentItems.find(
		(item) => item.threadId === threadId,
	);
	const replyClosed = selectedThread?.status === "Resolved";
	const canComment = capabilities.data?.canComment === true;
	const groupedComments = new Map<string, typeof commentItems>();
	for (const item of commentItems) {
		const group = groupedComments.get(item.threadId) ?? [];
		group.push(item);
		groupedComments.set(item.threadId, group);
	}

	return (
		<section className="drawer-content" aria-label="评论列表">
			{capabilities.data?.canComment === false && (
				<p className="feature-muted">当前权限仅允许查看评论。</p>
			)}
			<form
				className="comment-composer"
				onSubmit={(event) => {
					event.preventDefault();
					if (body.trim() && canComment && !replyClosed) addComment.mutate();
				}}
			>
				{threadId && (
					<div className="reply-context">
						{replyClosed
							? "这条讨论已关闭，请先重新打开后再回复。"
							: "正在回复一条评论"}
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
					disabled={!canComment || capabilities.isLoading}
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
					disabled={
						!body.trim() ||
						!canComment ||
						capabilities.isLoading ||
						addComment.isPending ||
						replyClosed
					}
				>
					{addComment.isPending ? "发送中…" : "发送评论"}
				</button>
			</form>
			{addComment.isError &&
				!(
					addComment.error instanceof DomApiError &&
					addComment.error.errorCode === "COMMENT_THREAD_RESOLVED"
				) && (
					<p className="feature-error" role="alert">
						评论发送失败，请重试。
					</p>
				)}
			{statusError && (
				<p className="feature-error" role="alert">
					{statusError}
				</p>
			)}
			{comments.isLoading && <p className="feature-muted">正在载入评论…</p>}
			{comments.isError && (
				<p className="feature-error" role="alert">
					评论暂时不可用。
				</p>
			)}
			{capabilities.isError && (
				<p className="feature-error" role="alert">
					无法读取文档权限，评论和状态操作已禁用。
				</p>
			)}
			{Array.from(groupedComments).map(([id, messages]) => {
				const root = messages[0];
				const isCreator = root.createdBy === account.data?.accountId;
				return (
					<article
						className="comment-thread-card"
						key={id}
						data-testid="comment-thread"
						data-status={root.status}
					>
						<header className="comment-thread-heading">
							<span>
								{root.status === "Resolved"
									? "已解决"
									: root.status === "Detached"
										? "原位置已失效"
										: "进行中"}
							</span>
							{(isCreator ||
								(root.status === "Resolved"
									? capabilities.data?.canReopenCommentThread === true
									: capabilities.data?.canResolveCommentThread === true)) &&
								root.status !== "Detached" && (
									<button
										type="button"
										className="comment-reply"
										data-testid={
											root.status === "Resolved"
												? "comment-thread-reopen"
												: "comment-thread-resolve"
										}
										disabled={changeThreadStatus.isPending}
										onClick={() =>
											changeThreadStatus.mutate({
												id,
												action:
													root.status === "Resolved" ? "reopen" : "resolve",
											})
										}
									>
										{root.status === "Resolved" ? "重新打开" : "解决"}
									</button>
								)}
						</header>
						{messages.map((item) => {
							const quote = anchorText(item.anchor);
							return (
								<div
									className="comment-card"
									key={item.commentId}
									data-testid="comment-row"
									data-jumped={
										jumpedCommentId === item.commentId ? "true" : undefined
									}
								>
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
									<time dateTime={item.createdAt}>
										{new Date(item.createdAt).toLocaleString()}
									</time>
								</div>
							);
						})}
						{root.status === "Resolved" && (
							<p
								className="feature-muted"
								data-testid="comment-thread-closed-hint"
							>
								这条讨论已关闭，请先重新打开后再回复。
							</p>
						)}
						<button
							type="button"
							className="comment-reply"
							disabled={root.status === "Resolved"}
							onClick={() => setThreadId(id)}
						>
							{root.status === "Resolved" ? "已关闭" : "回复此讨论"}
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
