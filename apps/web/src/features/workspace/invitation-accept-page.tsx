import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { client } from "../../shared/api/client";
import { resourceRuntime } from "../../shared/api/resource-runtime";
import "./invitation-accept.css";

function messageOf(error: unknown): string {
	return error instanceof Error ? error.message : "邀请暂时无法处理，请重试。";
}

export function InvitationAcceptPage() {
	const [params] = useSearchParams();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const [logoutNotice, setLogoutNotice] = useState("");
	const token = params.get("token")?.trim() ?? "";
	const returnPath = `/invite/accept?token=${encodeURIComponent(token)}`;
	const loginPath = `/login?continue=${encodeURIComponent(returnPath)}`;
	const account = useQuery({
		queryKey: ["account"],
		queryFn: () => client.me(),
	});
	const accept = useMutation({
		mutationFn: () => client.acceptWorkspaceInvitation({ token }),
		onSuccess: async (result) => {
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: ["account"] }),
				queryClient.invalidateQueries({ queryKey: ["workspaces"] }),
			]);
			return result;
		},
	});
	const logout = useMutation({
		mutationFn: async () => {
			const accountId = account.data?.accountId;
			if (!accountId) throw new Error("无法确认当前账号，已取消退出。");

			let unsyncedResources: Awaited<
				ReturnType<typeof resourceRuntime.listUnsyncedResources>
			>;
			try {
				unsyncedResources =
					await resourceRuntime.listUnsyncedResources(accountId);
			} catch (error) {
				throw new Error(
					`无法检查本地未同步草稿，已取消退出：${messageOf(error)}`,
				);
			}
			if (unsyncedResources.length > 0) {
				return { loggedOut: false, draftCount: unsyncedResources.length };
			}

			await client.logout();
			resourceRuntime.clearCachedAccountId();
			return { loggedOut: true, draftCount: 0 };
		},
		onSuccess: (result) => {
			if (!result.loggedOut) {
				setLogoutNotice(
					`发现 ${result.draftCount} 个含未同步修改的资源，已取消退出；草稿仍保留在此设备。请完成同步后再切换账号。`,
				);
				return;
			}
			navigate(loginPath);
		},
		onError: (error) => setLogoutNotice(messageOf(error)),
	});
	const acceptedWorkspaceId = accept.data?.workspaceId;

	return (
		<main className="invitation-accept-shell">
			<section className="invitation-accept-card">
				<p className="invitation-accept-eyebrow">WORKSPACE INVITATION</p>
				<div className="invitation-accept-mark" aria-hidden="true">
					↗
				</div>
				{acceptedWorkspaceId ? (
					<>
						<h1>你已加入工作区</h1>
						<p>邀请已接受。现在可以进入工作区查看项目与文档权限。</p>
						<button
							className="invitation-accept-primary"
							type="button"
							onClick={() =>
								navigate(
									`/workspace?workspaceId=${encodeURIComponent(acceptedWorkspaceId)}`,
								)
							}
						>
							进入工作区
						</button>
					</>
				) : token === "" ? (
					<>
						<h1>邀请链接无效</h1>
						<p>链接里没有邀请令牌，请联系邀请人重新生成链接。</p>
						<Link className="invitation-accept-secondary" to="/login">
							返回登录
						</Link>
					</>
				) : account.isLoading ? (
					<>
						<h1>正在验证邀请</h1>
						<p>正在确认当前登录账号与邀请状态。</p>
					</>
				) : account.isError ? (
					<>
						<h1>暂时无法验证账号</h1>
						<p>{messageOf(account.error)}</p>
						<button
							className="invitation-accept-secondary"
							type="button"
							onClick={() => void account.refetch()}
						>
							重试
						</button>
					</>
				) : account.data === null || account.data === undefined ? (
					<>
						<h1>接受工作区邀请</h1>
						<p>请先登录收到邀请的账号。登录成功后会回到此页面继续接受。</p>
						<Link className="invitation-accept-primary" to={loginPath}>
							登录并继续
						</Link>
					</>
				) : (
					<>
						<h1>接受工作区邀请</h1>
						<p>
							当前账号：<strong>{account.data.primaryEmail}</strong>
						</p>
						{account.data.accountStatus !== "Active" ? (
							<p className="invitation-accept-error">
								此账号尚未激活。完成邮箱验证后再接受邀请。
							</p>
						) : (
							<button
								className="invitation-accept-primary"
								type="button"
								disabled={accept.isPending}
								onClick={() => accept.mutate()}
							>
								{accept.isPending ? "正在接受…" : "接受邀请"}
							</button>
						)}
						<button
							className="invitation-accept-link-button"
							type="button"
							disabled={logout.isPending}
							onClick={() => {
								setLogoutNotice("");
								logout.mutate();
							}}
						>
							{logout.isPending ? "正在退出…" : "切换到其他账号"}
						</button>
					</>
				)}
				{accept.error && (
					<p className="invitation-accept-error">{messageOf(accept.error)}</p>
				)}
				{logoutNotice && (
					<p className="invitation-accept-error" role="alert">
						{logoutNotice}
					</p>
				)}
			</section>
		</main>
	);
}
