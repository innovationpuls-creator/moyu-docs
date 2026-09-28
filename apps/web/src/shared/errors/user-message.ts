/**
 * 面向用户的错误文案（唯一入口）。
 *
 * 后端错误信封（DomApiError）带稳定 messageKey / errorCode / category /
 * requestId；这里是它们到"用户看到的话"的映射：每一条都说明发生了什么、
 * 为什么（能解释的时候说一句导致原因）、以及用户接下来可以做什么。文案以
 * messageKey 为权威索引（contracts/errors/error-codes.yaml），未收录的码
 * 依次回退到 errorCode、错误分类，最后是未知错误兜底。
 */

export interface UserErrorView {
	/** 一句话标题，适合放在弹窗标题或告警条首行。 */
	title: string;
	/** 完整的人话：发生了什么 + 接下来可以怎么做。 */
	detail: string;
}

type ErrorLike = {
	messageKey?: string;
	errorCode?: string;
	category?: string;
	requestId?: string;
};

const MESSAGES: Record<string, UserErrorView> = {
	// ---- 登录与账号（Authentication）----
	"auth.error.invalidCredential": {
		title: "登录失败",
		detail:
			"邮箱或密码不正确，暂时进不去。可以先检查一遍拼写和大小写，或者点“忘记密码”重置后再试。",
	},
	"auth.error.sessionExpired": {
		title: "登录已过期",
		detail:
			"你的登录状态已经失效了，为了账号安全请重新登录。本机没同步完的内容还会保留，登录后会接着补上。",
	},
	"auth.error.sessionReplaced": {
		title: "账号已在别处登录",
		detail:
			"这个账号刚刚在另一台设备上登录，当前设备的会话被顶掉了。本地没有同步的内容不会丢，重新登录后会自动补上来。",
	},
	"auth.error.sessionNotAuthorized": {
		title: "登录状态无效",
		detail: "这次会话没有通过校验，重新登录后再继续吧。",
	},
	"auth.error.accountDisabled": {
		title: "账号不可用",
		detail: "这个账号当前不可用。如果你觉得是误判，可以联系管理员确认一下。",
	},
	"auth.error.accountInRecoveryMode": {
		title: "账号正在恢复中",
		detail:
			"账号进入了恢复模式，业务操作会暂时暂停。联系管理员处理恢复后再继续。",
	},
	"auth.error.passwordResetTokenInvalid": {
		title: "重置链接不能用",
		detail:
			"这个重置密码的链接已经失效，可能过期或者被用过了。回到登录页重新发起一次密码重置，用最新邮件里的链接。",
	},
	"auth.error.emailVerificationTokenInvalid": {
		title: "验证链接失效",
		detail:
			"这封邮件里的验证链接已经不能用了。重新发送一封验证邮件，点最新那封里的链接完成验证。",
	},
	"auth.error.recentAuthenticationRequired": {
		title: "需要重新验证身份",
		detail: "这是一项需要确认过身份才能做的操作，请重新登录一次再继续。",
	},
	"auth.error.rateLimited": {
		title: "操作太频繁了",
		detail: "你刚才点得太快，系统暂时拦了一下。歇一小会儿再试就行了。",
	},
	"integration.error.authRequired": {
		title: "还差一步授权",
		detail: "这个外部服务还没有授权连接，先去完成授权再使用。",
	},
	"integration.error.authUnauthorized": {
		title: "外部服务授权失效",
		detail: "这个外部服务的授权已经失效，重新授权一次再继续。",
	},

	// ---- 输入校验（Validation）----
	"auth.error.passwordTooWeak": {
		title: "密码不够安全",
		detail:
			"密码至少需要 12 位，把大小写字母和数字混着用会更安全，别人也更难猜。",
	},
	"auth.error.emailInvalid": {
		title: "邮箱格式不对",
		detail: "这个邮箱地址看起来不太对，检查一下拼写再提交。",
	},
	"workspace.error.nameInvalid": {
		title: "名字不合适",
		detail: "这个名字不符合要求，换一个 1 到 120 个字的名称就行。",
	},
	"permission.error.invitationEmailInvalid": {
		title: "邀请邮箱无效",
		detail: "填写的邀请邮箱格式不对，检查一下收件人地址。",
	},
	"permission.error.invitationExpiryInvalid": {
		title: "邀请有效期不对",
		detail: "邀请的有效期设置有问题，重新选一个到期时间。",
	},
	"share.error.expiryInvalid": {
		title: "分享有效期不对",
		detail: "分享链接的有效期设置有误，重新选一个到期时间。",
	},
	"comment.error.bodyInvalid": {
		title: "评论内容为空",
		detail: "评论内容不能为空，写下你想说的话再发送。",
	},
	"importexport.error.documentInvalid": {
		title: "文件内容无法识别",
		detail:
			"这个文件的内容格式没被识别出来，换个文件或者按支持的格式准备一份再导入。",
	},
	"importexport.error.payloadTooLarge": {
		title: "导入文件太大",
		detail: "要导入的文件超过了大小限制，拆小一点或者精简内容后再试。",
	},
	"importexport.error.resultTooLarge": {
		title: "导出内容太大",
		detail: "这次导出的内容超过了大小限制，可以按章节分多次导出。",
	},
	"task.error.paginationInvalid": {
		title: "分页参数不对",
		detail: "列表的分页参数有误，刷新列表后重试。",
	},

	// ---- 冲突（Conflict）----
	"auth.error.accountDeletionSoleOwner": {
		title: "账号删除被拦住了",
		detail:
			"你名下还有内容你是一手在管的人，先把这些内容移交或清理掉，之后才能删除账号。",
	},
	"auth.error.accountNotInDeletion": {
		title: "当前没有删除流程",
		detail: "这个账号并没有在删除流程里，不需要取消。",
	},
	"auth.error.idempotencyKeyConflict": {
		title: "这次操作已经提交过",
		detail: "同样的操作刚才已经执行过了，不要重复提交，刷新一下确认结果。",
	},
	"workspace.error.nameConflict": {
		title: "名字被占用了",
		detail: "已经有同名的工作区了，换一个名字就行。",
	},
	"workspace.error.parentInvalid": {
		title: "父级位置不对",
		detail: "这个位置不能作为上级目录，换一个目录试试。",
	},
	"workspace.error.folderCycle": {
		title: "文件夹出现了循环",
		detail: "文件夹不能放进它自己（或它的子文件夹）里，调整一下层级。",
	},
	"workspace.error.lifecycleConflict": {
		title: "当前状态不支持这个操作",
		detail: "内容现在的状态不允许执行这次操作，先恢复或归档后再试。",
	},
	"workspace.error.ownerTransferInvalid": {
		title: "所有权移交不成立",
		detail: "这次所有权移交的对象或状态有问题，换一位接收人再试。",
	},
	"workspace.error.requestIdMismatch": {
		title: "请求对不上",
		detail: "这次请求和上下文对不上，刷新页面重试。",
	},
	"integration.error.keyLimit": {
		title: "集成密钥到上限了",
		detail: "这个服务的集成密钥数量已经用完，删除不再用的旧密钥再添加新的。",
	},
	"permission.error.workspaceOwnerProtected": {
		title: "工作区所有者受保护",
		detail: "工作区的所有者不能被这样改动，调整成员方案后再试。",
	},
	"permission.error.projectOwnerProtected": {
		title: "项目所有者受保护",
		detail: "项目的所有者不能被这样改动，调整成员方案后再试。",
	},
	"permission.error.invitationExpired": {
		title: "邀请已过期",
		detail: "这份邀请已经过了有效时间，重新发一份邀请吧。",
	},
	"permission.error.invitationRevoked": {
		title: "邀请已撤销",
		detail: "这份邀请已经被撤销了，需要的话重新发一份。",
	},
	"permission.error.invitationStateConflict": {
		title: "邀请状态有冲突",
		detail: "这份邀请目前的状态不允许这个操作，刷新后重试。",
	},
	"permission.error.invitationCreatorUnauthorized": {
		title: "不能替邀请人操作",
		detail: "只有发出邀请的人能执行这个操作，联系对方处理。",
	},
	"permission.error.invitationScopeUnsupported": {
		title: "邀请范围不支持",
		detail: "这个范围的邀请当前还不支持，换一种邀请方式。",
	},
	"permission.error.targetAccountInactive": {
		title: "对方账号不可用",
		detail: "接收人账号当前不可用，确认账号状态后再邀请。",
	},
	"permission.error.projectLifecycleConflict": {
		title: "项目状态不支持",
		detail: "项目现在的状态不允许这个操作，调整后再试。",
	},
	"resource.error.nameConflict": {
		title: "名字被占用了",
		detail: "同一个位置已经有用这个名字的文档了，换一个名字就行。",
	},
	"resource.error.journalSequenceConflict": {
		title: "内容刚被更新过",
		detail:
			"你编辑的这篇文档刚刚被其他协作者更新过，刚才这次的修改没有保存上。系统已经帮你对齐到最新内容，直接继续编辑就行。",
	},
	"share.error.scopeInactive": {
		title: "分享范围不可用",
		detail: "这份分享当前的权限范围不允许这个操作，换个范围再试。",
	},
	"share.error.linkRevoked": {
		title: "分享链接已失效",
		detail: "这个分享链接已经被关闭了，需要的话重新生成一个分享链接。",
	},
	"comment.error.threadResolved": {
		title: "讨论已关闭",
		detail: "这条讨论已经标记为解决了，重新打开后才能继续回复。",
	},
	"comment.error.threadStateConflict": {
		title: "讨论状态冲突",
		detail: "这条讨论的状态刚刚发生变化，刷新后再操作即可。",
	},
	"task.error.notCancellable": {
		title: "任务不能取消",
		detail: "这个任务已经进入无法取消的阶段，等它完成即可。",
	},
	"task.error.cancelNotAccepted": {
		title: "取消没有被接受",
		detail: "任务当前没能接受取消请求，稍等片刻再试一次。",
	},
	"task.error.notRetryable": {
		title: "任务不能重试",
		detail: "这个任务不支持重新执行，可以重新发起一次新任务。",
	},
	"history.error.labelConflict": {
		title: "版本标签被占用",
		detail: "已经有版本用了这个标签，换一个标签名。",
	},

	// ---- 权限（Permission）----
	"workspace.error.projectReadOnly": {
		title: "项目是只读的",
		detail: "这个项目目前只能查看，不能修改。你可以正常浏览内容。",
	},
	"workspace.error.permissionDenied": {
		title: "没有权限",
		detail: "你没有执行这个操作所需的权限，可以请有权限的人帮忙处理。",
	},
	"workspace.error.activeAccountRequired": {
		title: "账号状态不允许",
		detail: "创建内容需要账号处于正常可用状态，先完成账号验证再来。",
	},
	"permission.error.invitationEmailMismatch": {
		title: "邮箱对不上",
		detail: "你登录用的邮箱和这份邀请不是同一个，换被邀请的账号登录后再接受。",
	},
	"permission.error.projectOwnerRequired": {
		title: "需要项目所有者",
		detail: "这个操作只有项目所有者能做，请所有者来操作。",
	},
	"resource.error.permissionDenied": {
		title: "没有这篇文档的权限",
		detail:
			"你看不到这篇文档的内容，它可能没有分享给你。可以找文档的所有者把你加为协作者。",
	},
	"share.error.manageDenied": {
		title: "不能管理这个分享",
		detail: "你没有管理这份分享的权限，联系分享的创建者处理。",
	},
	"comment.error.permissionDenied": {
		title: "不能操作这条评论",
		detail: "你没有权限执行这次评论操作，找讨论的发起人帮忙。",
	},

	// ---- 找不到（NotFound）----
	"auth.error.accountNotFound": {
		title: "账号不存在",
		detail: "没有找到这个账号，可能是邮箱填错了，或者先注册一个再登录。",
	},
	"workspace.error.notFound": {
		title: "工作区不存在",
		detail: "这个工作区可能已被删除，或者链接有误。回列表确认一下。",
	},
	"workspace.error.projectNotFound": {
		title: "项目不存在",
		detail: "这个项目可能已被移动或删除，或者链接有误。回列表确认一下。",
	},
	"workspace.error.folderNotFound": {
		title: "文件夹不存在",
		detail: "这个文件夹可能已被删除或移动，刷新列表看看。",
	},
	"webhook.error.subscriptionNotFound": {
		title: "订阅不存在",
		detail: "这个回调订阅已经不存在了，重新创建一个订阅。",
	},
	"integration.error.keyNotFound": {
		title: "集成密钥不存在",
		detail: "这个集成密钥已经不存在了，重新配置一次集成。",
	},
	"permission.error.invitationInvalid": {
		title: "邀请无效",
		detail: "这份邀请没法用，可能已经过期或被撤销。请对方重新发一份。",
	},
	"permission.error.invitationNotFound": {
		title: "邀请不存在",
		detail: "没有找到这份邀请，可能已经失效。让邀请人重新发一份。",
	},
	"resource.error.notFound": {
		title: "文档不存在",
		detail:
			"这篇文档可能已被移动或删除，或者链接本身有误。回列表看看，或找发链接的人确认一下。",
	},
	"share.error.linkNotFound": {
		title: "分享链接不存在",
		detail: "这个分享链接打不开，可能已经失效。找分享者要一个新的链接。",
	},
	"importexport.error.resultNotFound": {
		title: "导出结果不存在",
		detail: "导出结果还没准备好或者已被清理，重新发起一次导出。",
	},
	"ai.error.changesetNotFound": {
		title: "改动内容不存在",
		detail: "这份 AI 改动内容已经找不到了，重新生成一次。",
	},
	"comment.error.notFound": {
		title: "评论不存在",
		detail: "这条评论可能已被删除，刷新页面看看。",
	},
	"comment.error.threadNotFound": {
		title: "讨论不存在",
		detail: "这条讨论可能已被删除，刷新页面看看。",
	},
	"asset.error.notFound": {
		title: "附件不存在",
		detail: "这个附件可能已被删除或清理，重新上传一份。",
	},
	"task.error.notFound": {
		title: "任务不存在",
		detail: "这个任务可能已被清理，回到任务列表看看。",
	},
	"notification.error.notFound": {
		title: "通知不存在",
		detail: "这条通知可能已被删除，刷新列表看看。",
	},

	// ---- 服务暂时不可用（Unavailable / DependencyFailure）----
	"workspace.error.authorizationUnavailable": {
		title: "权限服务暂时没响应",
		detail:
			"没能确认你对工作区的权限，这次操作没有执行。服务恢复后会自动重试，不用重复提交。",
	},
	"resource.error.authorizationUnavailable": {
		title: "权限服务暂时没响应",
		detail:
			"没能确认你对这篇文档的权限，这次操作没有执行。网络或服务恢复后会自动重试，不用重复提交。",
	},
	"importexport.error.storageUnavailable": {
		title: "文件存储暂时不可用",
		detail: "存取文件的存储服务暂时没响应，稍等片刻再试，已上传的内容不会丢。",
	},

	// ---- 错误分类兜底 ----
	"__category.Authentication": {
		title: "登录状态有问题",
		detail: "请重新登录后再试；如果反复出现，把页面上的错误编号告诉管理员。",
	},
	"__category.Validation": {
		title: "输入需要检查",
		detail: "提交的内容没有通过校验，按提示修改后重新提交。",
	},
	"__category.Permission": {
		title: "没有权限",
		detail: "你没有执行这个操作所需的权限，可以请有权限的人帮忙。",
	},
	"__category.NotFound": {
		title: "找不到相关内容",
		detail: "要找的内容不存在或已被删除，回到列表确认一下。",
	},
	"__category.Conflict": {
		title: "操作发生冲突",
		detail: "内容刚才发生了变化，刷新页面后再试一次。",
	},
	"__category.RateLimit": {
		title: "操作太频繁了",
		detail: "你操作得太快，系统暂时拦了一下，稍等一会儿再试。",
	},
	"__category.Timeout": {
		title: "请求超时了",
		detail: "服务器这次没有及时回应，稍等片刻重试。",
	},
	"__category.DependencyFailure": {
		title: "依赖服务暂时不可用",
		detail: "这次操作依赖的服务暂时没有响应，稍后会自动重试。",
	},
	"__category.Unavailable": {
		title: "服务暂时不可用",
		detail: "服务暂时没响应，稍等片刻再试。",
	},
	"__category.Internal": {
		title: "服务器出了点问题",
		detail:
			"服务器处理这次请求时出了点问题，请稍后再试；如果反复出现，把错误编号告诉管理员。",
	},
};

const UNKNOWN: UserErrorView = {
	title: "出了点问题",
	detail:
		"这次操作没有成功，请稍后再试。如果反复出现，把页面上的错误编号告诉管理员。",
};

/**
 * 把一个后端错误信封翻译成用户可读的「标题 + 说明 + 下一步」。
 * 查找顺序：messageKey → errorCode → 错误分类 → 未知兜底。
 */
export function userErrorView(error: ErrorLike): UserErrorView {
	const byKey =
		(error?.messageKey && MESSAGES[error.messageKey]) ||
		(error?.errorCode && MESSAGES[error.errorCode]) ||
		null;
	if (byKey) return byKey;
	const byCategory =
		error?.category && MESSAGES[`__category.${error.category}`];
	if (byCategory) return byCategory;
	return {
		...UNKNOWN,
		detail: error?.requestId
			? `${UNKNOWN.detail}（错误编号 ${error.requestId}）`
			: UNKNOWN.detail,
	};
}
