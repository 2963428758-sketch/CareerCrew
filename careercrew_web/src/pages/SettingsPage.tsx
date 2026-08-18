import { useRef, useState, useSyncExternalStore } from "react"
import { Camera, KeyRound, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ProfilePanel } from "@/components/data/ProfilePanel"
import { MemoryPanel } from "@/components/data/MemoryPanel"
import { MemorySettingsPanel } from "@/components/data/MemorySettingsPanel"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { AvatarImage } from "@/components/UserMenu"
import { Tooltip } from "@/components/ui/tooltip"
import { NameEditor } from "@/components/DisplayNameEditor"
import { RoleBadge } from "@/components/RoleBadge"
import { SETTINGS_SECTIONS } from "@/components/app-shell/settingsSections"
import { apiFetch, getAuthSnapshot, logout, subscribeAuth } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"
import { bumpAvatarNonce, useAvatar } from "@/lib/avatar"
import { cn } from "@/lib/utils"

/** 头像底色：按用户名哈希从品牌色板里取，稳定且不重复（无上传头像时兜底）。 */
const AVATAR_COLORS = ["#0D9488", "#7C3AED", "#D97706", "#BE185D", "#2563EB"]

function avatarColor(username: string) {
  let h = 0
  for (const c of username) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

/**
 * 设置页内容：与主页面一致的布局——50px 面包屑工作区头部 + 820px 居中内容列。
 * 设置导航在外侧 SettingsSidebar（圆角工作区之外，与主侧边栏同构）。
 */
export default function SettingsPage({ section }: { section: string }) {
  const active = SETTINGS_SECTIONS.find((s) => s.key === section) ?? SETTINGS_SECTIONS[0]

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader title={active.label} subtitle={active.desc} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[820px] px-6 py-6">
          {active.key === "profile" && <ProfilePanel />}
          {active.key === "memory" && <MemoryPanel />}
          {active.key === "memory-settings" && <MemorySettingsPanel />}
          {active.key === "account" && <AccountPanel />}
          {active.key === "about" && <AboutPanel />}
        </div>
      </div>
    </div>
  )
}

// ── 账号面板（头像上传 + 账号信息 + 修改密码） ──

function AccountPanel() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const user = auth.user
  const [renaming, setRenaming] = useState(false)
  if (!user) return null

  const initial = (user.display_name || user.username).charAt(0).toUpperCase()
  const displayName = user.display_name || user.username

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-[13px] font-medium">账号信息</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <AvatarUpload userId={user.id} username={user.username} initial={initial} />
            <div className="min-w-0 flex-1">
              {renaming ? (
                <NameEditor
                  current={displayName}
                  onDone={() => setRenaming(false)}
                  inputClassName="bg-workspace"
                />
              ) : (
                <p className="flex items-center gap-1.5 text-[13px] font-medium">
                  <span className="truncate">{displayName}</span>
                  <RoleBadge role={user.role} />
                  <Tooltip label="修改名字">
                    <button
                      type="button"
                      onClick={() => setRenaming(true)}
                      aria-label="修改名字"
                      className="shrink-0 rounded-[5px] p-0.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                  </Tooltip>
                </p>
              )}
              <p className="mt-0.5 text-[12px] text-ink-faint">@{user.username}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <ChangePasswordCard />
    </div>
  )
}

/** 头像展示 + 上传（PNG/JPG/WebP/GIF，≤5MB）。 */
function AvatarUpload({ userId, username, initial }: { userId: string; username: string; initial: string }) {
  const avatarUrl = useAvatar(userId)
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)

  const handleFile = async (file: File) => {
    setError("")
    setSuccess(false)
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
      setError("仅支持 PNG / JPG / WebP / GIF 格式的头像")
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("头像不能超过 5MB")
      return
    }
    setUploading(true)
    try {
      const form = new FormData()
      form.append("file", file)
      const resp = await apiFetch("/api/auth/avatar", { method: "POST", body: form })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "头像上传失败，请重试"))
      bumpAvatarNonce() // 使侧边栏/本页头像失效并重取
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
    } catch (e) {
      setError(networkErrorText(e, "头像上传失败，请检查网络后重试"))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ""
    }
  }

  return (
    <div className="flex shrink-0 flex-col items-center gap-1.5">
      <div className="relative">
        <AvatarImage
          url={avatarUrl}
          fallbackColor={avatarColor(username)}
          initial={initial}
          size="h-12 w-12 text-[16px]"
        />
        <Tooltip label="上传头像">
          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            aria-label="上传头像"
            className="absolute -bottom-0.5 -right-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-[var(--border-soft)] bg-workspace text-ink-faint shadow-prompt transition-colors duration-100 hover:text-ink disabled:opacity-50"
          >
            {uploading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Camera className="h-3 w-3" />}
          </button>
        </Tooltip>
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void handleFile(f)
          }}
        />
      </div>
      {(success || error) && (
        <p className={cn("max-w-[180px] text-center text-[11px] font-medium", success ? "text-green-600" : "text-destructive")}>
          {success ? "✓ 已更新" : error}
        </p>
      )}
    </div>
  )
}

export function ChangePasswordCard() {
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [newPasswordError, setNewPasswordError] = useState("")
  const [success, setSuccess] = useState(false)

  // 与后端密码策略一致：8-64 位，必须同时包含字母和数字
  const policyValid = (p: string) => /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/.test(p)

  const submit = async () => {
    if (!oldPassword) { setError("请输入当前密码"); return }
    if (!policyValid(newPassword)) {
      setError("")
      setNewPasswordError("新密码需为 8-64 位，且同时包含字母和数字")
      return
    }
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
      if (!resp.ok) throw new Error(await apiErrorText(resp, "密码修改失败，请重试"))
      setOldPassword("")
      setNewPassword("")
      setConfirm("")
      setSuccess(true)
      // 密码已修改：撤销所有会话并跳回登录页
      setTimeout(() => void logout(), 1000)
    } catch (e) {
      setError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
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
            {success && <p className="text-green-600">✓ 密码已修改，请重新登录…</p>}
            {error && <p className="text-destructive">{error}</p>}
          </div>
        )}
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-ink-soft">当前密码</span>
          <Input type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} placeholder="请输入当前密码" autoComplete="current-password" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-ink-soft">新密码</span>
          <div className="relative">
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => {
                setNewPassword(e.target.value)
                if (newPasswordError) setNewPasswordError("")
              }}
              onBlur={() => {
                if (!policyValid(newPassword)) {
                  setNewPasswordError("新密码需为 8-64 位，且同时包含字母和数字")
                } else {
                  setNewPasswordError("")
                }
              }}
              placeholder="8-64 位，包含字母和数字"
              autoComplete="new-password"
              aria-invalid={newPasswordError ? true : undefined}
              aria-describedby={newPasswordError ? "new-password-error" : undefined}
            />
            {newPasswordError && (
              <div
                id="new-password-error"
                role="alert"
                className="absolute left-0 top-full z-20 mt-1 w-max max-w-[min(280px,calc(100vw-48px))] rounded-[7px] border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-[11.5px] font-medium text-destructive shadow-popover sm:left-full sm:top-1/2 sm:ml-2 sm:mt-0 sm:-translate-y-1/2"
              >
                {newPasswordError}
              </div>
            )}
          </div>
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-ink-soft">确认新密码</span>
          <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="再次输入新密码" autoComplete="new-password" />
        </label>
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
