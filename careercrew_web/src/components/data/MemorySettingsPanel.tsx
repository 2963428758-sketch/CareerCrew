import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorCard } from "@/components/data/shared"
import { cn } from "@/lib/utils"
import { apiFetch, getAuthSnapshot } from "@/lib/auth"

interface MemorySettingsData {
  enabled: boolean
  feature_enabled: boolean
  global: { enabled: boolean; generate: boolean; use: boolean }
}

interface MemoryPolicyData {
  global: { enabled: boolean; generate: boolean; use: boolean }
  user: { user_id: string; enabled: boolean; generate: boolean; use: boolean }
  effective: { enabled: boolean; generate: boolean; use: boolean }
}

/** 记忆设置面板（全局开关 + 用户级策略），供设置页「记忆设置」独立区块使用。 */
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
      apiFetch("/api/settings/memory").then((r) => r.json()),
      apiFetch(`/api/memory/policy?user_id=${getAuthSnapshot().user?.id ?? "u_001"}`).then((r) => r.json()),
    ])
      .then(([s, p]) => {
        setSettings(s as MemorySettingsData)
        setPolicy(p as MemoryPolicyData)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const put = async (url: string, body: Record<string, unknown>) => {
    const resp = await apiFetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const b = await resp.json().catch(() => null)
      throw new Error(b?.detail || `HTTP ${resp.status}`)
    }
    return resp.json()
  }

  // 点击开关即保存：乐观更新本地状态，成功后用服务端返回（含生效值）回填
  const updateGlobalEnabled = async (v: boolean) => {
    if (!settings) return
    setSaveError("")
    setSettings({ ...settings, enabled: v })
    try {
      const s = await put("/api/settings/memory", { enabled: v })
      setSettings(s as MemorySettingsData)
    } catch (e) {
      setSaveError((e as Error).message)
      load()
    }
  }

  const updateUserPolicy = async (patch: Partial<MemoryPolicyData["user"]>) => {
    if (!policy) return
    setSaveError("")
    const next = { ...policy, user: { ...policy.user, ...patch } }
    setPolicy(next)
    try {
      const p = await put(`/api/memory/policy?user_id=${getAuthSnapshot().user?.id ?? "u_001"}`, {
        enabled: next.user.enabled,
        generate: next.user.generate,
        use: next.user.use,
      })
      setPolicy(p as MemoryPolicyData)
    } catch (e) {
      setSaveError((e as Error).message)
      load()
    }
  }

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!settings || !policy) return null

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-[13px] font-medium">全局记忆开关</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <ToggleRow
            label="启用记忆（全局）"
            desc="关闭时记忆完全不写入/不注入；开启后仍需用户级策略允许。"
            checked={settings.enabled}
            onChange={(v) => updateGlobalEnabled(v)}
          />
          {saveError && <p className="text-[12px] font-medium text-destructive">保存失败：{saveError}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-[13px] font-medium">我的记忆策略</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <ToggleRow
            label="允许记忆"
            desc="开启后允许写入与注入本用户记忆。"
            checked={policy.user.enabled}
            onChange={(v) => updateUserPolicy({ enabled: v })}
          />
          <ToggleRow
            label="生成记忆"
            desc="是否把本用户对话沉淀为记忆。"
            checked={policy.user.generate}
            onChange={(v) => updateUserPolicy({ generate: v })}
          />
          <ToggleRow
            label="使用记忆"
            desc="是否在会话中自动注入本用户历史记忆。"
            checked={policy.user.use}
            onChange={(v) => updateUserPolicy({ use: v })}
          />
          {saveError && <p className="text-[12px] font-medium text-destructive">保存失败：{saveError}</p>}
        </CardContent>
      </Card>
    </div>
  )
}

function ToggleRow({ label, desc, checked, onChange }: {
  label: string
  desc: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-3 rounded-[8px] border border-[var(--border-soft)] px-3 py-2.5 text-left transition-colors duration-100 hover:bg-[var(--hover)]"
    >
      <div>
        <p className="text-[13px] font-medium">{label}</p>
        <p className="text-[12px] text-ink-faint">{desc}</p>
      </div>
      <span className={cn(
        "relative h-5 w-9 shrink-0 rounded-full transition-colors duration-100",
        checked ? "bg-button-ink" : "bg-surface-3"
      )}>
        <span className={cn(
          "absolute top-0.5 h-4 w-4 rounded-full bg-workspace shadow-[var(--shadow-prompt)] transition-transform duration-100",
          checked ? "translate-x-4" : "translate-x-0.5"
        )} />
      </span>
    </button>
  )
}
