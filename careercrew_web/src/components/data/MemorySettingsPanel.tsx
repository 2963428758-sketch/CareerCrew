import { useEffect, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorCard } from "@/components/data/shared"
import { cn } from "@/lib/utils"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

interface MemorySettingsData {
  enabled: boolean
  feature_enabled: boolean
  global: { enabled: boolean; generate: boolean; use: boolean }
}

interface MemoryPolicyData {
  global: { enabled: boolean; generate: boolean; use: boolean }
  user: { user_id: string; enabled: boolean; generate: boolean; use: boolean }
  effective: {
    enabled?: boolean; generate?: boolean; use?: boolean
    memory_enabled?: boolean; can_generate?: boolean; can_use?: boolean
    can_manual_save?: boolean; can_consolidate?: boolean
  }
}

/** 设置页只显示实际生效的状态，父级关闭时不再留下看似开启的子开关。 */
export function MemorySettingsPanel() {
  const [settings, setSettings] = useState<MemorySettingsData | null>(null)
  const [policy, setPolicy] = useState<MemoryPolicyData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [saveError, setSaveError] = useState("")

  const load = () => {
    setLoading(true)
    setError("")
    Promise.all([
      apiFetch("/api/settings/memory").then(async (r) => {
        if (!r.ok) throw new Error(await apiErrorText(r, "加载记忆设置失败"))
        return r.json()
      }),
      apiFetch("/api/memory/policy").then(async (r) => {
        if (!r.ok) throw new Error(await apiErrorText(r, "加载记忆策略失败"))
        return r.json()
      }),
    ]).then(([s, p]) => {
      setSettings(s as MemorySettingsData)
      setPolicy(p as MemoryPolicyData)
    }).catch((e) => setError(networkErrorText(e, "网络连接失败，请检查网络后重试")))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const put = async (url: string, body: Record<string, unknown>) => {
    const resp = await apiFetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    if (!resp.ok) throw new Error(await apiErrorText(resp, "保存失败"))
    return resp.json()
  }

  const updateGlobalEnabled = async (enabled: boolean) => {
    if (!settings) return
    setSaveError("")
    setSettings({ ...settings, enabled })
    try { setSettings(await put("/api/settings/memory", { enabled }) as MemorySettingsData) }
    catch (e) { setSaveError(networkErrorText(e, "保存失败，请稍后重试")); load() }
  }

  const updateUserPolicy = async (patch: Partial<MemoryPolicyData["user"]>) => {
    if (!policy) return
    setSaveError("")
    const next = { ...policy, user: { ...policy.user, ...patch } }
    setPolicy(next)
    try {
      setPolicy(await put("/api/memory/policy", {
        enabled: next.user.enabled, generate: next.user.generate, use: next.user.use,
      }) as MemoryPolicyData)
    } catch (e) { setSaveError(networkErrorText(e, "保存失败，请稍后重试")); load() }
  }

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!settings || !policy) return null

  const effective = policy.effective
  const enabled = effective.memory_enabled ?? effective.enabled ?? false
  const canGenerate = effective.can_generate ?? effective.generate ?? false
  const canUse = effective.can_use ?? effective.use ?? false
  const globalBlocked = !settings.enabled
  const userBlocked = globalBlocked || !enabled

  return <div className="space-y-5">
    {saveError && <p role="alert" className="text-[12px] font-medium text-destructive">保存失败：{saveError}</p>}
    <div>
      <h3 className="mb-2 text-[13px] font-medium text-ink">全局记忆开关</h3>
      <div className="overflow-hidden rounded-[12px] border border-[var(--border-soft)] bg-workspace">
        <ToggleRow label="启用记忆（全局）" desc="关闭后不会生成、检索或注入长期记忆；聊天记录仍会正常保存。" checked={settings.enabled} onChange={updateGlobalEnabled} />
      </div>
    </div>

    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3"><h3 className="text-[13px] font-medium text-ink">我的记忆策略</h3><span className={`text-[11px] font-medium ${enabled ? "text-primary" : "text-ink-faint"}`}>{enabled ? "当前生效" : "当前未生效"}</span></div>
      {globalBlocked && <p className="mb-2 rounded-[8px] bg-surface-2 px-3 py-2 text-[12px] text-ink-soft">全局记忆当前关闭，以下策略暂不生效。</p>}
      <div className="overflow-hidden rounded-[12px] border border-[var(--border-soft)] bg-workspace">
        <ToggleRow label="允许记忆" desc={globalBlocked ? "需由管理员先开启全局记忆。" : "控制本账号的长期记忆总开关。"} checked={enabled} disabled={globalBlocked} onChange={(value) => updateUserPolicy({ enabled: value })} />
        <ToggleRow label="生成记忆" desc={userBlocked ? "先开启上方的记忆总开关后才能调整。" : "允许 Agent 保存确认过的长期事实和关键事件。"} checked={canGenerate} disabled={userBlocked} onChange={(value) => updateUserPolicy({ generate: value })} />
        <ToggleRow label="使用记忆" desc={userBlocked ? "先开启上方的记忆总开关后才能调整。" : "允许 Agent 在需要时读取并注入相关长期记忆。"} checked={canUse} disabled={userBlocked} onChange={(value) => updateUserPolicy({ use: value })} />
      </div>
    </div>
  </div>
}

function ToggleRow({ label, desc, checked, disabled = false, onChange }: { label: string; desc: string; checked: boolean; disabled?: boolean; onChange: (value: boolean) => void }) {
  return <button onClick={() => onChange(!checked)} disabled={disabled} aria-label={label} aria-checked={checked} className={cn("flex min-h-14 w-full items-center justify-between gap-3 border-b border-[var(--border-soft)] px-3.5 py-2.5 text-left transition-colors last:border-0", disabled ? "cursor-not-allowed opacity-55" : "hover:bg-[var(--hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40")}><div><p className="text-[13px] font-medium">{label}</p><p className="text-[12px] text-ink-faint">{desc}</p></div><span className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors duration-150", checked ? "bg-button-ink" : "bg-surface-3")}><span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-workspace shadow-[var(--shadow-prompt)] transition-transform duration-150", checked ? "translate-x-4" : "translate-x-0.5")} /></span></button>
}
