import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { RefreshCw, ShieldCheck, Gauge, Trash2, UserPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { InputDialog } from "@/components/ui/InputDialog"
import { CreateUserDialog } from "@/components/CreateUserDialog"
import { apiFetch, getAuthSnapshot, subscribeAuth } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"
import { notifyError, notifyInfo, notifySuccess } from "@/lib/toastBus"
import { cn } from "@/lib/utils"

interface AccountItem {
  id: string
  username: string
  role: "admin" | "user" | "quality_reviewer"
  status: "active" | "disabled"
  token_version: number
  created_at: string
  updated_at: string
}

const ROLE_LABEL: Record<string, string> = { admin: "管理员", user: "普通用户", quality_reviewer: "质检员" }
const STATUS_LABEL: Record<string, string> = { active: "正常", disabled: "已禁用" }

/**
 * 用户管理面板（无页面头部，可嵌入设置页或独立页面）：
 * 账号列表 + 升/降级、启用/禁用、重置密码、新建用户。
 */
export function UserManagementPanel() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const [accounts, setAccounts] = useState<AccountItem[]>([])
  const [total, setTotal] = useState(0)
  const [creating, setCreating] = useState(false)
  /** 待删除确认的账号（自定义确认框，替代 window.confirm） */
  const [confirmDelete, setConfirmDelete] = useState<AccountItem | null>(null)
  /** 删除请求进行中：清理业务数据可能较慢，期间确认框保持「删除中」不可关闭 */
  const [deleting, setDeleting] = useState(false)
  /** 待重置密码的账号（自定义输入弹窗，替代 window.prompt） */
  const [resetTarget, setResetTarget] = useState<AccountItem | null>(null)
  /** 批量操作选中的账号 ID（自己不可选中：所有管理端点都拒绝操作自己） */
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmBatchDelete, setConfirmBatchDelete] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)

  const me = auth.user?.id

  const selectable = accounts.filter((a) => a.id !== me)
  const selectedCount = selectable.filter((a) => selected.has(a.id)).length
  const allSelected = selectable.length > 0 && selectable.every((a) => selected.has(a.id))
  const someSelected = selectable.some((a) => selected.has(a.id))
  const headCheckRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (headCheckRef.current) headCheckRef.current.indeterminate = someSelected && !allSelected
  }, [someSelected, allSelected])

  const toggleRow = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(selectable.map((a) => a.id)))
  }

  const refresh = () => {
    setSelected(new Set())
    apiFetch("/api/auth/users?page=1&page_size=100")
      .then(async (r) => {
        if (!r.ok) throw new Error(await apiErrorText(r, "加载账号列表失败"))
        const data = await r.json()
        setAccounts(data.items)
        setTotal(data.total)
      })
      .catch((e) => notifyError(networkErrorText(e, "加载账号列表失败，请检查网络后重试")))
  }

  useEffect(() => { void refresh() }, [])

  const patch = async (id: string, body: Record<string, string>) => {
    try {
      const resp = await apiFetch(`/api/auth/users/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!resp.ok) { notifyError(await apiErrorText(resp, "更新账号失败，请重试")); return }
      const data = await resp.json()
      notifySuccess(`已更新 ${data.username}`)
      refresh()
    } catch (e) {
      notifyError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
    }
  }

  /** 提交重置密码：返回错误文案由弹窗内红字提示，正常返回即关闭 */
  const submitResetPassword = async (id: string, next: string): Promise<string | undefined> => {
    if (next !== "" && !(next.length >= 8 && next.length <= 64 && /[A-Za-z]/.test(next) && /\d/.test(next))) {
      return "自定义密码需为 8-64 位，且同时包含字母和数字；留空则使用默认密码 123456"
    }
    try {
      const resp = await apiFetch(`/api/auth/users/${id}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: next === "" ? null : next }),
      })
      if (!resp.ok) return await apiErrorText(resp, "重置密码失败，请重试")
      notifySuccess("密码已重置（下次登录需修改密码），该用户所有会话已失效")
    } catch (e) {
      return networkErrorText(e, "网络连接失败，请检查网络后重试")
    }
  }

  /** 删除账号：请求期间确认框显示「删除中…」，完成后关闭并提示结果 */
  const deleteUser = async (id: string, username: string) => {
    setDeleting(true)
    try {
      const resp = await apiFetch(`/api/auth/users/${id}`, { method: "DELETE" })
      if (!resp.ok) { notifyError(await apiErrorText(resp, "删除账号失败，请重试")); return }
      const data = await resp.json()
      notifySuccess(`已删除账号 ${data.username ?? username} 及其全部业务数据`)
    } catch (e) {
      notifyError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
    } finally {
      setDeleting(false)
      setConfirmDelete(null)
      refresh()
    }
  }

  /** 批量启用/禁用：串行执行避免并发绕过「最后一名管理员」保护；已是目标状态的跳过 */
  const runBatchStatus = async (status: "active" | "disabled") => {
    const targets = selectable.filter((a) => selected.has(a.id) && a.status !== status)
    if (targets.length === 0) { notifyInfo("所选账号均已处于该状态"); return }
    setBatchBusy(true)
    let okCount = 0
    const failed: string[] = []
    for (const a of targets) {
      try {
        const resp = await apiFetch(`/api/auth/users/${a.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        })
        if (!resp.ok) failed.push(a.username)
        else okCount++
      } catch {
        failed.push(a.username)
      }
    }
    setBatchBusy(false)
    refresh()
    const label = status === "disabled" ? "禁用" : "启用"
    if (failed.length === 0) notifySuccess(`已${label} ${okCount} 个账号`)
    else notifyError(`已${label} ${okCount} 个，失败 ${failed.length} 个（${failed.join("、")}）`)
  }

  /** 批量删除：串行执行，逐个清理业务数据并汇总结果 */
  const runBatchDelete = async () => {
    const targets = selectable.filter((a) => selected.has(a.id))
    if (targets.length === 0) return
    setBatchBusy(true)
    setDeleting(true)
    let okCount = 0
    const failed: string[] = []
    for (const a of targets) {
      try {
        const resp = await apiFetch(`/api/auth/users/${a.id}`, { method: "DELETE" })
        if (!resp.ok) failed.push(a.username)
        else okCount++
      } catch {
        failed.push(a.username)
      }
    }
    setDeleting(false)
    setBatchBusy(false)
    setConfirmBatchDelete(false)
    refresh()
    if (failed.length === 0) notifySuccess(`已删除 ${okCount} 个账号及其全部业务数据`)
    else notifyError(`成功 ${okCount} 个，失败 ${failed.length} 个（${failed.join("、")}）`)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-ink-faint">共 {total} 个账号</p>
        <div className="flex shrink-0 gap-1.5">
          <Button variant="outline" size="sm" onClick={refresh}>
            <RefreshCw className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />刷新
          </Button>
          <Button size="sm" onClick={() => setCreating(true)}>
            <UserPlus className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />新建用户
          </Button>
        </div>
      </div>

      {selectedCount > 0 && (
        <div className="flex items-center gap-2 rounded-[8px] border border-primary/30 bg-primary/5 px-3 py-2">
          <span className="text-[13px] font-medium text-ink">已选 {selectedCount} 个账号</span>
          <div className="ml-auto flex gap-1.5">
            <Button size="sm" variant="outline" disabled={batchBusy} onClick={() => void runBatchStatus("active")}>
              批量启用
            </Button>
            <Button size="sm" variant="outline" disabled={batchBusy} onClick={() => void runBatchStatus("disabled")}>
              批量禁用
            </Button>
            <Button size="sm" variant="outline" className="text-destructive" disabled={batchBusy}
              onClick={() => setConfirmBatchDelete(true)}>
              <Trash2 className="mr-1 h-3 w-3" strokeWidth={1.7} />批量删除
            </Button>
            <Button size="sm" variant="ghost" disabled={batchBusy} onClick={() => setSelected(new Set())}>
              取消选择
            </Button>
          </div>
        </div>
      )}

      {creating && (
        <CreateUserDialog
          open={creating}
          onClose={() => setCreating(false)}
          onCreated={(name) => {
            setCreating(false)
            notifySuccess(`已创建账号 ${name}`)
            refresh()
          }}
        />
      )}

      <Card>
        <CardContent className="p-0">
          <table className="w-full table-fixed text-[13px]">
            <colgroup>
              <col className="w-[44px]" />{/* 勾选 */}
              {/* 用户名/角色/状态/创建时间：无固定宽度，四列均分剩余空间，间隔一致 */}
              <col />
              <col />
              <col />
              <col />
              <col className="w-[360px]" />{/* 操作：贴合按钮区宽度 */}
            </colgroup>
            <thead>
              <tr className="border-b border-[var(--border-soft)] text-left text-[11px] font-medium text-ink-faint">
                <th className="px-2 py-2.5 text-center align-middle">
                  <input
                    ref={headCheckRef}
                    type="checkbox"
                    aria-label="全选"
                    checked={allSelected}
                    onChange={toggleAll}
                    disabled={selectable.length === 0 || batchBusy}
                    className="h-3.5 w-3.5 cursor-pointer accent-primary"
                  />
                </th>
                <th className="px-4 py-2.5 text-center font-medium align-middle">用户名</th>
                <th className="px-4 py-2.5 text-center font-medium align-middle">角色</th>
                <th className="px-4 py-2.5 text-center font-medium align-middle">状态</th>
                <th className="px-4 py-2.5 text-center font-medium align-middle">创建时间</th>
                <th className="px-4 py-2.5 font-medium align-middle">操作</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className="border-b border-[var(--border-soft)] last:border-0">
                  <td className="px-2 py-2.5 text-center align-middle">
                    <input
                      type="checkbox"
                      aria-label={`选择 ${a.username}`}
                      checked={selected.has(a.id)}
                      onChange={() => toggleRow(a.id)}
                      disabled={a.id === me || batchBusy}
                      className="h-3.5 w-3.5 cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-40"
                    />
                  </td>
                  <td className="px-4 py-2.5 text-center font-medium align-middle">{a.username}</td>
                  <td className="px-4 py-2.5 text-center align-middle">
                    <span className={cn("inline-flex items-center gap-1 rounded-[5px] px-1.5 py-0.5 text-[11px]",
                      a.role === "admin" ? "bg-primary/10 text-primary"
                        : a.role === "quality_reviewer" ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                        : "bg-surface-2 text-ink-soft")}>
                      {a.role === "admin" && <ShieldCheck className="h-3 w-3" />}
                      {a.role === "quality_reviewer" && <Gauge className="h-3 w-3" />}
                      {ROLE_LABEL[a.role]}
                    </span>
                  </td>
                  <td className={cn("px-4 py-2.5 text-center align-middle", a.status === "disabled" && "text-destructive")}>{STATUS_LABEL[a.status]}</td>
                  <td className="px-4 py-2.5 text-center text-[12px] text-ink-faint align-middle">{a.created_at.slice(0, 10)}</td>
                  <td className="px-4 py-2.5 align-middle">
                    {a.id === me ? (
                      <span className="text-[12px] text-ink-faint">当前账号</span>
                    ) : (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <select
                          aria-label="角色"
                          value={a.role}
                          onChange={(e) => patch(a.id, { role: e.target.value })}
                          className="h-7 rounded-[7px] border border-input bg-workspace px-1.5 text-[12px] outline-none transition-colors duration-100 focus-visible:ring-2 focus-visible:ring-ring/40"
                        >
                          <option value="user">普通用户</option>
                          <option value="quality_reviewer">质检员</option>
                          <option value="admin">管理员</option>
                        </select>
                        <Button size="sm" variant="outline" className="h-7 px-2 text-[12px]"
                          onClick={() => patch(a.id, { status: a.status === "active" ? "disabled" : "active" })}>
                          {a.status === "active" ? "禁用" : "启用"}
                        </Button>
                        <Button size="sm" variant="outline" className="h-7 px-2 text-[12px]" onClick={() => setResetTarget(a)}>
                          重置密码
                        </Button>
                        <Button size="sm" variant="outline" className="h-7 px-2 text-[12px] text-destructive"
                          onClick={() => setConfirmDelete(a)}>
                          <Trash2 className="mr-1 h-3 w-3" strokeWidth={1.7} />删除
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {accounts.length === 0 && <p className="px-4 py-8 text-center text-[13px] text-ink-faint">暂无账号</p>}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmBatchDelete}
        title={`删除选中的 ${selectedCount} 个账号？`}
        message={"将删除这些账号及其全部业务数据（会话、记忆、反馈、附件），数据较多时会稍慢，且无法恢复。"}
        confirmLabel="全部删除"
        pendingLabel="删除中…"
        pending={deleting}
        closeOnConfirm={false}
        onConfirm={() => void runBatchDelete()}
        onClose={() => { if (!deleting) setConfirmBatchDelete(false) }}
      />

      <InputDialog
        open={resetTarget !== null}
        title={`重置「${resetTarget?.username ?? ""}」的登录密码`}
        message={"留空 = 重置为默认密码 123456（下次登录需改密）；\n自定义需 8-64 位且同时包含字母和数字。重置后该用户所有会话立即失效。"}
        type="password"
        placeholder="输入新密码（留空使用默认）"
        confirmLabel="重置密码"
        pendingLabel="重置中…"
        autoComplete="new-password"
        onSubmit={(next) => {
          if (!resetTarget) return
          return submitResetPassword(resetTarget.id, next)
        }}
        onClose={() => setResetTarget(null)}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        title={`删除账号「${confirmDelete?.username ?? ""}」？`}
        message={"删除后将一并清除该用户的全部业务数据（会话、记忆、反馈、附件），数据较多时会稍慢，且无法恢复。"}
        confirmLabel="删除账号"
        pendingLabel="删除中…"
        pending={deleting}
        closeOnConfirm={false}
        onConfirm={() => { if (confirmDelete) void deleteUser(confirmDelete.id, confirmDelete.username) }}
        onClose={() => { if (!deleting) setConfirmDelete(null) }}
      />
    </div>
  )
}
