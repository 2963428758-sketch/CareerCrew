import { useEffect, useState, useSyncExternalStore } from "react"
import { RefreshCw, ShieldCheck, UserPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
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
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<"user" | "admin">("user")

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

  const createUser = async () => {
    if (!username.trim() || password.length < 12) {
      setError("用户名必填，密码至少 12 个字符")
      return
    }
    setError("")
    const resp = await apiFetch("/api/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.trim(), password, role }),
    })
    const data = await resp.json()
    if (!resp.ok) { setError(data.detail || `HTTP ${resp.status}`); return }
    setCreating(false)
    setUsername("")
    setPassword("")
    setRole("user")
    setNotice(`已创建账号 ${data.username}`)
    refresh()
  }

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
    const next = window.prompt(`为账号输入新密码（至少 12 个字符）：`)
    if (!next || next.length < 12) { setError("密码至少 12 个字符"); return }
    const resp = await apiFetch(`/api/auth/users/${id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: next }),
    })
    if (!resp.ok) { const data = await resp.json().catch(() => ({})); setError(data.detail || `HTTP ${resp.status}`); return }
    setNotice("密码已重置，该用户所有会话已失效")
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">用户管理</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">开户、角色、启用/禁用与重置密码（共 {total} 个账号）</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={refresh}><RefreshCw className="mr-1 h-3.5 w-3.5" />刷新</Button>
          <Button size="sm" onClick={() => setCreating((v) => !v)}><UserPlus className="mr-1 h-3.5 w-3.5" />新建用户</Button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error && <p className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
        {notice && <p className="mb-3 rounded-md border border-green-600/40 bg-green-600/10 px-3 py-2 text-sm text-green-700">{notice}</p>}

        {creating && (
          <Card className="mb-4">
            <CardHeader className="pb-2"><CardTitle className="text-sm font-semibold">新建账号</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-muted-foreground">用户名
                <Input aria-label="用户名" value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 h-9 w-44 text-sm" placeholder="3-64 位字母数字" />
              </label>
              <label className="text-xs text-muted-foreground">密码
                <Input aria-label="密码" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 h-9 w-44 text-sm" placeholder="至少 12 个字符" />
              </label>
              <label className="text-xs text-muted-foreground">角色
                <select value={role} onChange={(e) => setRole(e.target.value as "user" | "admin")} className="mt-1 h-9 w-32 rounded-md border border-border bg-card px-2 text-sm">
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
              </label>
              <Button size="sm" onClick={createUser}>创建</Button>
              <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>取消</Button>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium">用户名</th>
                  <th className="px-4 py-2.5 font-medium">角色</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium">创建时间</th>
                  <th className="px-4 py-2.5 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id} className="border-b last:border-0">
                    <td className="px-4 py-2.5 font-medium">{a.username}</td>
                    <td className="px-4 py-2.5">
                      <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px]", a.role === "admin" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground")}>
                        {a.role === "admin" && <ShieldCheck className="h-3 w-3" />}{ROLE_LABEL[a.role]}
                      </span>
                    </td>
                    <td className={cn("px-4 py-2.5", a.status === "disabled" && "text-destructive")}>{STATUS_LABEL[a.status]}</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{a.created_at.slice(0, 10)}</td>
                    <td className="px-4 py-2.5">
                      {a.id === me ? (
                        <span className="text-xs text-muted-foreground">当前账号</span>
                      ) : (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                            onClick={() => patch(a.id, { role: a.role === "admin" ? "user" : "admin" })}>
                            {a.role === "admin" ? "降为普通用户" : "升为管理员"}
                          </Button>
                          <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                            onClick={() => patch(a.id, { status: a.status === "active" ? "disabled" : "active" })}>
                            {a.status === "active" ? "禁用" : "启用"}
                          </Button>
                          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => resetPassword(a.id)}>
                            重置密码
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {accounts.length === 0 && <p className="px-4 py-8 text-center text-sm text-muted-foreground">暂无账号</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
