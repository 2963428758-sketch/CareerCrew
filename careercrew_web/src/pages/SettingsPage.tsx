import { useState, useSyncExternalStore, type ComponentType } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Brain, Info, KeyRound, ShieldCheck, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { DataSettingsContent } from "@/pages/DataPage"
import { UserMenu } from "@/components/UserMenu"
import { apiFetch, getAuthSnapshot, subscribeAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

const SECTIONS: { key: string; label: string; desc: string; icon: ComponentType<{ className?: string; strokeWidth?: number }> }[] = [
  { key: "data", label: "数据与记忆", desc: "用户画像、记忆查看与记忆策略设置", icon: Brain },
  { key: "account", label: "账号", desc: "账号信息与密码修改", icon: User },
  { key: "about", label: "关于", desc: "版本与应用信息", icon: Info },
]

/** 设置页：左侧设置导航 + 右侧内容区（Codex 风格：导航低调、内容舒展）。 */
export default function SettingsPage() {
  const navigate = useNavigate()
  const [section, setSection] = useState("data")
  const active = SECTIONS.find((s) => s.key === section) ?? SECTIONS[0]

  return (
    <div className="flex h-full">
      <aside className="flex w-52 shrink-0 flex-col border-r border-[var(--border-soft)] bg-surface-1">
        <div className="flex h-[50px] shrink-0 items-center gap-2 border-b border-[var(--border-soft)] px-3">
          <button
            onClick={() => navigate("/")}
            className="rounded-[7px] p-1.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
            title="返回"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={1.7} />
          </button>
          <span className="text-[13px] font-medium text-ink">设置</span>
        </div>

        <nav className="flex flex-col gap-[2px] p-2">
          {SECTIONS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSection(s.key)}
              className={cn(
                "flex h-[34px] items-center gap-[9px] rounded-[7px] px-[9px] text-left text-[13px] font-[450] transition-colors duration-100",
                section === s.key
                  ? "bg-[var(--active)] text-ink"
                  : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
              )}
            >
              <s.icon
                className={cn("h-4 w-4 shrink-0", section === s.key ? "text-ink" : "text-ink-faint")}
                strokeWidth={1.7}
              />
              {s.label}
            </button>
          ))}
        </nav>

        {/* 设置页侧边栏底部同样保留用户区 */}
        <div className="mt-auto px-2 pb-2">
          <UserMenu />
        </div>
      </aside>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[760px] px-6 py-6">
          <header className="mb-6">
            <h1 className="text-[20px] font-[560] leading-[1.3] tracking-[-0.015em] text-ink">{active.label}</h1>
            <p className="mt-0.5 text-[13px] text-ink-soft">{active.desc}</p>
          </header>

          {section === "data" && <DataSettingsContent />}
          {section === "account" && <AccountPanel />}
          {section === "about" && <AboutPanel />}
        </div>
      </div>
    </div>
  )
}

// ── 账号面板 ──

function AccountPanel() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const user = auth.user
  if (!user) return null

  const initial = user.username.charAt(0).toUpperCase()

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-[13px] font-medium">账号信息</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-[15px] font-medium text-primary-foreground">
              {initial}
            </span>
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-[13px] font-medium">
                {user.username}
                {user.role === "admin" && (
                  <span className="inline-flex items-center gap-1 rounded-[5px] bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                    <ShieldCheck className="h-3 w-3" />管理员
                  </span>
                )}
              </p>
              <p className="mt-0.5 truncate text-[12px] text-ink-faint">用户 ID：{user.id}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <ChangePasswordCard />
    </div>
  )
}

function ChangePasswordCard() {
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)

  const submit = async () => {
    if (!oldPassword) { setError("请输入当前密码"); return }
    const policyOk = newPassword.length >= 8 && newPassword.length <= 64 && /[A-Za-z]/.test(newPassword) && /\d/.test(newPassword)
    if (!policyOk) { setError("新密码需为 8-64 位，且同时包含字母和数字"); return }
    if (newPassword !== confirm) { setError("两次输入的新密码不一致"); return }
    setError("")
    setSuccess(false)
    setSaving(true)
    try {
      const resp = await apiFetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
      setOldPassword("")
      setNewPassword("")
      setConfirm("")
      setSuccess(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-1.5 text-[13px] font-medium">
          <KeyRound className="h-3.5 w-3.5" />修改密码
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {(success || error) && (
          <div className="rounded-[7px] border border-[var(--border-soft)] px-3 py-2 text-[12px]">
            {success && <p className="text-green-600">✓ 密码已修改，其他设备的登录会话已失效</p>}
            {error && <p className="text-destructive">{error}</p>}
          </div>
        )}
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-ink-soft">当前密码</span>
          <Input type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} autoComplete="current-password" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink-soft">新密码</span>
            <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="8-64 位，含字母和数字" autoComplete="new-password" />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink-soft">确认新密码</span>
            <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="再输一遍" autoComplete="new-password" />
          </label>
        </div>
        <div className="flex justify-end">
          <Button size="sm" onClick={submit} disabled={saving}>
            {saving ? "保存中…" : "保存"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ── 关于面板 ──

function AboutPanel() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-10 text-center">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="5" r="2.5" fill="#0D9488" />
          <circle cx="5" cy="17" r="2.5" fill="#D97706" />
          <circle cx="19" cy="17" r="2.5" fill="#7C3AED" />
          <path d="M12 7.5L5.5 14.5M12 7.5L18.5 14.5M7 17h10" stroke="#2D3340" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <div>
          <h2 className="text-[16px] font-medium text-ink">CareerCrew</h2>
          <p className="mt-1 text-[12px] text-ink-faint">版本 0.1.0</p>
        </div>
        <p className="max-w-sm text-[13px] leading-relaxed text-ink-soft">
          求职全流程 AI 助手：职位匹配、简历优化、面试练习与会诊，知识库问答与记忆沉淀贯穿始终。
        </p>
      </CardContent>
    </Card>
  )
}
