import { useEffect, useState, useSyncExternalStore } from "react"
import { RefreshCw, ShieldCheck, UserPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { CreateUserDialog } from "@/components/CreateUserDialog"
import { apiFetch, getAuthSnapshot, subscribeAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

interface AccountItem {
  id: string
  username: string
  role: "admin" | "user"
  status: "active" | "disabled"
  token_version: number
  created_at: string
  updated_at: string
}

const ROLE_LABEL: Record<string, string> = { admin: "管理员", user: "普通用户" }
const STATUS_LABEL: Record<string, string> = { active: "正常", disabled: "已禁用" }

export default function AdminUsersPage() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const [accounts, setAccounts] = useState<AccountItem[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [creating, setCreating] = useState(false)

  const me = auth.user?.id

  const refresh = () => {
    setError("")
    setNotice("")
    apiFetch("/api/auth/users?page=1&page_size=100")
      .then(async (r) => {
        const data = await r.json()
        if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
        setAccounts(data.items)
        setTotal(data.total)
      })
      .catch((e) => setError((e as Error).message))
  }

  useEffect(() => { refresh() }, [])

  const patch = async (id: string, body: Record<string, string>) => {
    const resp = await apiFetch(`/api/auth/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    const data = await resp.json()
    if (!resp.ok) { setError(data.detail || `HTTP ${resp.status}`); return }
    setNotice(`已更新 ${data.username}`)
    refresh()
  }

  const resetPassword = async (id: string) => {
    const next = window.prompt("为该账号设置新密码（留空=默认 123456；自定义需 8-64 位且含字母和数字）：")
    if (next === null) return
    if (next !== "" && !(next.length >= 8 && next.length <= 64 && /[A-Za-z]/.test(next) && /\d/.test(next))) {
      setError("自定义密码需为 8-64 位，且同时包含字母和数字")
      return
    }
    const resp = await apiFetch(`/api/auth/users/${id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: next === "" ? null : next }),
    })
    if (!resp.ok) { const data = await resp.json().catch(() => ({})); setError(data.detail || `HTTP ${resp.status}`); return }
    setNotice("密码已重置（下次登录需修改密码），该用户所有会话已失效")
  }

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        title="用户管理"
        subtitle={`开户、角色、启用/禁用与重置密码（共 ${total} 个账号）`}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={refresh}><RefreshCw className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />刷新</Button>
            <Button size="sm" onClick={() => setCreating(true)}><UserPlus className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />新建用户</Button>
          </>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error && <p className="mb-3 rounded-[8px] border border-destructive/40 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">{error}</p>}
        {notice && <p className="mb-3 rounded-[8px] border border-green-600/40 bg-green-600/10 px-3 py-2 text-[13px] text-green-700">{notice}</p>}

        {creating && (
          <CreateUserDialog
            open={creating}
            onClose={() => setCreating(false)}
            onCreated={(name) => {
              setCreating(false)
              setNotice(`已创建账号 ${name}`)
              refresh()
            }}
          />
        )}

        <Card>
          <CardContent className="p-0">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-[var(--border-soft)] text-left text-[11px] font-medium text-ink-faint">
                  <th className="px-4 py-2.5 font-medium">用户名</th>
                  <th className="px-4 py-2.5 font-medium">角色</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium">创建时间</th>
                  <th className="px-4 py-2.5 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id} className="border-b border-[var(--border-soft)] last:border-0">
                    <td className="px-4 py-2.5 font-medium">{a.username}</td>
                    <td className="px-4 py-2.5">
                      <span className={cn("inline-flex items-center gap-1 rounded-[5px] px-1.5 py-0.5 text-[11px]", a.role === "admin" ? "bg-primary/10 text-primary" : "bg-surface-2 text-ink-soft")}>
                        {a.role === "admin" && <ShieldCheck className="h-3 w-3" />}{ROLE_LABEL[a.role]}
                      </span>
                    </td>
                    <td className={cn("px-4 py-2.5", a.status === "disabled" && "text-destructive")}>{STATUS_LABEL[a.status]}</td>
                    <td className="px-4 py-2.5 text-[12px] text-ink-faint">{a.created_at.slice(0, 10)}</td>
                    <td className="px-4 py-2.5">
                      {a.id === me ? (
                        <span className="text-[12px] text-ink-faint">当前账号</span>
                      ) : (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Button size="sm" variant="outline" className="h-7 px-2 text-[12px]"
                            onClick={() => patch(a.id, { role: a.role === "admin" ? "user" : "admin" })}>
                            {a.role === "admin" ? "降为普通用户" : "升为管理员"}
                          </Button>
                          <Button size="sm" variant="outline" className="h-7 px-2 text-[12px]"
                            onClick={() => patch(a.id, { status: a.status === "active" ? "disabled" : "active" })}>
                            {a.status === "active" ? "禁用" : "启用"}
                          </Button>
                          <Button size="sm" variant="outline" className="h-7 px-2 text-[12px]" onClick={() => resetPassword(a.id)}>
                            重置密码
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
      </div>
    </div>
  )
}
