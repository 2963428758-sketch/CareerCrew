import { useEffect, useState } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tooltip } from "@/components/ui/tooltip"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

interface CreateUserDialogProps {
  open: boolean
  onClose: () => void
  /** 创建成功后回调：传入新账号用户名，由父组件刷新列表并提示。 */
  onCreated: (username: string) => void
}

/** "用户管理"里的新建账号弹窗。 */
export function CreateUserDialog({ open, onClose, onCreated }: CreateUserDialogProps) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<"user" | "admin" | "quality_reviewer">("user")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // 每次打开时清空上一次的填写内容与错误提示
  useEffect(() => {
    if (open) {
      setUsername("")
      setPassword("")
      setRole("user")
      setError("")
    }
  }, [open])

  // Esc 关闭 + 锁定背景滚动
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  if (!open) return null

  const submit = async () => {
    if (!username.trim()) {
      setError("用户名必填")
      return
    }
    if (password && !(password.length >= 8 && password.length <= 64 && /[A-Za-z]/.test(password) && /\d/.test(password))) {
      setError("自定义密码需为 8-64 位，且同时包含字母和数字；留空则使用默认密码 123456")
      return
    }
    setError("")
    setSubmitting(true)
    try {
      const resp = await apiFetch("/api/auth/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password: password || null, role }),
      })
      if (!resp.ok) {
        setError(await apiErrorText(resp, "创建账号失败，请重试"))
        return
      }
      const data = await resp.json()
      onCreated(data.username)
    } catch (e) {
      setError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose()
      }}
    >
      <div className="w-full max-w-md overflow-hidden rounded-[12px] border border-[var(--border-soft)] bg-workspace shadow-popover stream-fade-in">
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border-soft)] px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-[15px] font-medium text-ink">新建账号</h3>
            <p className="mt-0.5 text-[12px] text-ink-faint">密码留空时使用默认 123456，该账号首次登录需改密</p>
          </div>
          <Tooltip label="关闭">
            <button
              onClick={onClose}
              disabled={submitting}
              aria-label="关闭"
              className="shrink-0 rounded-[7px] p-1 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:opacity-50"
            >
              <X className="h-4 w-4" />
            </button>
          </Tooltip>
        </div>

        <div className="space-y-3 px-5 py-4">
          {error && (
            <p className="rounded-[7px] border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</p>
          )}
          <label className="block">
            <span className="mb-1 flex items-center gap-1 text-[12.5px] font-medium text-ink">
              用户名 <span className="text-destructive">*</span>
            </span>
            <Input
              aria-label="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="3-64 位字母数字"
              autoFocus
            />
          </label>
          <label className="block">
            <span className="mb-1 flex items-center gap-1 text-[12.5px] font-medium text-ink">密码（可选）</span>
            <Input
              aria-label="密码"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="留空默认 123456（首登需改密）；自定义密码可直接登录"
            />
          </label>
          <label className="block">
            <span className="mb-1 flex items-center gap-1 text-[12.5px] font-medium text-ink">角色</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "user" | "admin" | "quality_reviewer")}
              className="h-9 w-full rounded-[7px] border border-input bg-workspace px-3 text-[13px] outline-none transition-colors duration-100 focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              <option value="user">普通用户</option>
              <option value="quality_reviewer">质检员</option>
              <option value="admin">管理员</option>
            </select>
          </label>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-soft)] px-5 py-3">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button size="sm" onClick={submit} disabled={submitting}>
            {submitting ? "创建中…" : "创建"}
          </Button>
        </div>
      </div>
    </div>
  )
}
