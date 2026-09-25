import type {
	CommentThreadStatus,
	DomClient,
	ReopenCommentThreadResponse,
	ResolveCommentThreadResponse,
} from "@dom/client-sdk";

export interface CommentThreadStatusAccess {
	actorAccountId: string;
	threadCreatorAccountId: string;
	canResolveCommentThread: boolean;
	canReopenCommentThread: boolean;
}

export interface ReplyAvailability {
	allowed: boolean;
	message: string | null;
}

export interface CommentThreadStatusControlOptions {
	resourceId: string;
	threadId: string;
	status: CommentThreadStatus;
	access: CommentThreadStatusAccess;
	client: Pick<DomClient, "resolveCommentThread" | "reopenCommentThread">;
	onStatusChange?: (
		response: ResolveCommentThreadResponse | ReopenCommentThreadResponse,
	) => void;
	onError?: (error: unknown) => void;
}

export interface CommentThreadStatusControl {
	element: HTMLElement;
	readonly status: CommentThreadStatus;
	readonly replyAvailability: ReplyAvailability;
	resolve(): Promise<ResolveCommentThreadResponse>;
	reopen(): Promise<ReopenCommentThreadResponse>;
}

const RESOLVED_REPLY_MESSAGE = "这条讨论已解决，请先重新打开后再回复。";

export function createCommentThreadStatusControl(
	options: CommentThreadStatusControlOptions,
): CommentThreadStatusControl {
	let currentStatus = options.status;
	let pending = false;
	let feedbackText = "";

	const element = document.createElement("div");
	element.className = "comment-thread-status-control";
	element.dataset.testid = "comment-thread-status";
	element.style.display = "flex";
	element.style.alignItems = "center";
	element.style.gap = "8px";

	const statusLabel = document.createElement("span");
	statusLabel.dataset.testid = "comment-thread-status-label";
	statusLabel.setAttribute("aria-live", "polite");

	const actionHost = document.createElement("span");
	actionHost.className = "comment-thread-status-actions";
	const feedback = document.createElement("span");
	feedback.dataset.testid = "comment-thread-status-feedback";
	feedback.setAttribute("role", "status");
	feedback.setAttribute("aria-live", "polite");
	element.append(statusLabel, actionHost, feedback);

	const isCreator =
		options.access.actorAccountId === options.access.threadCreatorAccountId;
	const mayResolve = isCreator || options.access.canResolveCommentThread;
	const mayReopen = isCreator || options.access.canReopenCommentThread;

	function render(): void {
		element.dataset.status = currentStatus;
		statusLabel.textContent =
			currentStatus === "Resolved"
				? "已解决"
				: currentStatus === "Detached"
					? "原评论位置已不存在"
					: "进行中";
		feedback.textContent = feedbackText;
		actionHost.replaceChildren();

		if (currentStatus === "Resolved" ? mayReopen : mayResolve) {
			const button = document.createElement("button");
			button.type = "button";
			button.textContent = currentStatus === "Resolved" ? "重新打开" : "解决";
			button.dataset.testid =
				currentStatus === "Resolved"
					? "comment-thread-reopen"
					: "comment-thread-resolve";
			button.disabled = pending;
			button.addEventListener("click", () => {
				const action =
					currentStatus === "Resolved" ? control.reopen() : control.resolve();
				void action.catch((error: unknown) => options.onError?.(error));
			});
			actionHost.append(button);
		}
	}

	async function submit<
		Result extends ResolveCommentThreadResponse | ReopenCommentThreadResponse,
	>(request: () => Promise<Result>): Promise<Result> {
		pending = true;
		feedbackText = "";
		render();
		let result: Result;
		try {
			result = await request();
		} catch (error) {
			feedbackText = errorMessage(error);
			throw error;
		} finally {
			pending = false;
			render();
		}
		currentStatus = result.status;
		feedbackText = "";
		render();
		options.onStatusChange?.(result);
		return result;
	}

	const control: CommentThreadStatusControl = {
		element,
		get status() {
			return currentStatus;
		},
		get replyAvailability() {
			return currentStatus === "Resolved"
				? { allowed: false, message: RESOLVED_REPLY_MESSAGE }
				: { allowed: true, message: null };
		},
		resolve(): Promise<ResolveCommentThreadResponse> {
			if (!mayResolve) {
				return Promise.reject(new Error("Missing comment.resolve capability"));
			}
			return submit(() =>
				options.client.resolveCommentThread(
					options.resourceId,
					options.threadId,
				),
			);
		},
		reopen(): Promise<ReopenCommentThreadResponse> {
			if (!mayReopen) {
				return Promise.reject(new Error("Missing comment.reopen capability"));
			}
			return submit(() =>
				options.client.reopenCommentThread(
					options.resourceId,
					options.threadId,
				),
			);
		},
	};

	render();
	return control;
}

function errorMessage(error: unknown): string {
	if (error && typeof error === "object" && "errorCode" in error) {
		return `状态更新失败（${String(error.errorCode)}）。`;
	}
	return "状态更新失败，请重试。";
}
