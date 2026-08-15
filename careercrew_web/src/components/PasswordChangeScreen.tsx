import { useState } from "react"
import { KeyRound, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { apiFetch, logout, restoreSession } from "@/lib/auth"

/** 首次登录（或管理员重置密码后）的强制改密页：改完自动恢复会话。 */
export default function PasswordChangeScreen() {
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const valid = (p: string) =>
    p.length >= 8 && p.length <= 64 && /[A-Za-z]/.test(p) && /\d/.test(p)

  const submit = async () => {
    setError("")
    if (!valid(password)) {
      setError("密码需为 8-64 位，且同时包含字母和数字")
      return
    }
    if (password !== confirm) {
      setError("两次输入的密码不一致")
      return
    }
    setBusy(true)
    try {
      const resp = await apiFetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: password }),
      })
      const data = await resp.json().catch(() => null)
      if (!resp.ok) {
        setError((data as { detail?: string } | null)?.detail || `修改失败（HTTP ${resp.status}）`)
        return
      }
      // 改密会 bump token_version：重新刷新会话换取新 token 并清除强制改密标记
      await restoreSession()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-shell p-5">
      <Card className="w-full max-w-md rounded-[14px] shadow-workspace">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-[15px] font-medium text-ink">
            <KeyRound className="h-4 w-4 text-primary" />
            首次登录，请设置新密码
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-[12.5px] text-ink-soft">
            为保障账号安全，使用默认密码登录后必须先设置新密码才能继续使用系统。
          </p>
          <label className="text-[12px] font-medium text-ink-soft">新密码
            <Input
              aria-label="新密码"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1"
              placeholder="8-64 位，包含字母和数字"
              autoFocus
            />
          </label>
          <label className="text-[12px] font-medium text-ink-soft">确认新密码
            <Input
              aria-label="确认新密码"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void submit() }}
              className="mt-1"
              placeholder="再次输入新密码"
            />
          </label>
          {error && <p className="text-[12px] font-medium text-destructive">{error}</p>}
          <div className="flex items-center justify-between pt-1">
            <button
              onClick={() => { void logout() }}
              className="flex items-center gap-1 text-[12px] text-ink-faint transition-colors duration-100 hover:text-ink"
            >
              <LogOut className="h-3.5 w-3.5" />退出登录
            </button>
            <Button size="sm" onClick={submit} disabled={busy}>
              {busy ? "保存中…" : "保存新密码"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
