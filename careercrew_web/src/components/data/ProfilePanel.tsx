import { useEffect, useState } from "react"
import { Building2, Wallet, MapPin, Pencil, Check, X } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorCard } from "@/components/data/shared"
import { useChatStore } from "@/store/chatStore"
import { apiFetch, getAuthSnapshot } from "@/lib/auth"

interface ProfileData {
  user_id?: string
  profile?: { skills?: string[]; direction?: string; level?: string; experience_years?: number | null }
  target_companies?: string[]
  preferences?: { salary_min?: number | null; salary_max?: number | null; city?: string[]; work_mode?: string }
}

function useFetch<T>(url: string) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiFetch(url)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => null)
          throw new Error(body?.detail || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [url])
  return { data, loading, error }
}

/** 能力画像面板（可编辑），供设置页「能力画像」独立区块使用。 */
export function ProfilePanel() {
  const nonce = useChatStore((s) => s.profileNonce)
  const url = `/api/profile?v=${nonce}`
  const { data, loading, error } = useFetch<ProfileData>(url)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [saveSuccess, setSaveSuccess] = useState(false)

  useEffect(() => {
    if (data) {
      const p = data.profile || {}
      const pref = data.preferences || {}
      setForm({
        "profile.direction": p.direction || "",
        "profile.level": p.level || "",
        "profile.experience_years": p.experience_years ? String(p.experience_years) : "",
        "profile.skills": (p.skills || []).join("、"),
        "preferences.salary_min": pref.salary_min ? String(pref.salary_min) : "",
        "preferences.salary_max": pref.salary_max ? String(pref.salary_max) : "",
        "preferences.city": (pref.city || []).join("、"),
        "preferences.work_mode": pref.work_mode || "",
        "target_companies": (data.target_companies || []).join("、"),
      })
    }
  }, [data])

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!data) return null

  const p = data.profile || {}
  const pref = data.preferences || {}

  const handleSave = async () => {
    setSaving(true)
    setSaveError("")
    setSaveSuccess(false)
    // 始终发送所有字段（空值对应清空：字符串→""、列表→[]、数字→null）
    const fields: Record<string, unknown> = {
      "profile.direction": form["profile.direction"] || "",
      "profile.level": form["profile.level"] || "",
      "profile.experience_years": form["profile.experience_years"] ? parseInt(form["profile.experience_years"]) : null,
      "profile.skills": form["profile.skills"] ? form["profile.skills"].split(/[、,，\s]+/).filter(Boolean) : [],
      "preferences.salary_min": form["preferences.salary_min"] ? parseInt(form["preferences.salary_min"]) : null,
      "preferences.salary_max": form["preferences.salary_max"] ? parseInt(form["preferences.salary_max"]) : null,
      "preferences.city": form["preferences.city"] ? form["preferences.city"].split(/[、,，\s]+/).filter(Boolean) : [],
      "preferences.work_mode": form["preferences.work_mode"] || "",
      "target_companies": form["target_companies"] ? form["target_companies"].split(/[、,，\s]+/).filter(Boolean) : [],
    }

    try {
      const resp = await apiFetch(`/api/profile?user_id=${getAuthSnapshot().user?.id ?? "u_001"}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      useChatStore.getState().bumpProfileNonce()
      setEditing(false)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (e) {
      setSaveError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-[13px] font-medium">能力画像</CardTitle>
          {editing ? (
            <div className="flex gap-1">
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                <X className="mr-1 h-3 w-3" />取消
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                <Check className="mr-1 h-3 w-3" />{saving ? "保存中" : "保存"}
              </Button>
            </div>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              <Pencil className="mr-1 h-3 w-3" />编辑
            </Button>
          )}
        </CardHeader>
        {(saveSuccess || saveError) && (
          <div className="px-4 pb-2">
            {saveSuccess && <p className="text-[12px] font-medium text-green-600">✓ 已保存</p>}
            {saveError && <p className="text-[12px] font-medium text-destructive">保存失败：{saveError}</p>}
          </div>
        )}
        <CardContent className="space-y-2.5">
          {editing ? (
            <>
              <EditRow label="方向" value={form["profile.direction"] || ""} onChange={(v) => setForm({ ...form, "profile.direction": v })} placeholder="如：大模型应用" />
              <EditRow label="级别" value={form["profile.level"] || ""} onChange={(v) => setForm({ ...form, "profile.level": v })} placeholder="如：初级/中级/高级" />
              <EditRow label="经验" value={form["profile.experience_years"] || ""} onChange={(v) => setForm({ ...form, "profile.experience_years": v })} placeholder="如：3" />
              <EditRow label="技能" value={form["profile.skills"] || ""} onChange={(v) => setForm({ ...form, "profile.skills": v })} placeholder="用、分隔，如：Java、RAG、Agent" />
            </>
          ) : (
            <>
              <Row label="方向" value={p.direction} />
              <Row label="级别" value={p.level} />
              <Row label="经验" value={p.experience_years ? `${p.experience_years} 年` : null} />
              <div className="flex items-start gap-3">
                <span className="w-16 shrink-0 pt-0.5 text-[13px] font-medium text-ink-soft">技能</span>
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px]">
                  {p.skills && p.skills.length > 0
                    ? p.skills.map((s, i) => (
                      <span key={s}>
                        {i > 0 && <span className="text-ink-faint opacity-40">·</span>}
                        {s}
                      </span>
                    ))
                    : <span className="text-ink-faint">暂无</span>}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-[13px] font-medium">求职偏好</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {editing ? (
            <div className="grid grid-cols-2 gap-3">
              <EditRow label="薪资下限(K)" value={form["preferences.salary_min"] || ""} onChange={(v) => setForm({ ...form, "preferences.salary_min": v })} placeholder="如：30" />
              <EditRow label="薪资上限(K)" value={form["preferences.salary_max"] || ""} onChange={(v) => setForm({ ...form, "preferences.salary_max": v })} placeholder="如：50" />
              <EditRow label="城市" value={form["preferences.city"] || ""} onChange={(v) => setForm({ ...form, "preferences.city": v })} placeholder="用、分隔" />
              <EditRow label="工作模式" value={form["preferences.work_mode"] || ""} onChange={(v) => setForm({ ...form, "preferences.work_mode": v })} placeholder="如：远程/现场/混合" />
              <EditRow label="目标公司" value={form["target_companies"] || ""} onChange={(v) => setForm({ ...form, "target_companies": v })} placeholder="用、分隔" />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <IconField icon={Wallet} label="薪资范围" value={
                pref.salary_min || pref.salary_max
                  ? `${pref.salary_min ?? "?"}-${pref.salary_max ?? "?"}K`
                  : null
              } />
              <IconField icon={MapPin} label="城市" value={pref.city?.length ? pref.city.join("、") : null} />
              <IconField icon={Building2} label="工作模式" value={pref.work_mode || null} />
              {data.target_companies && data.target_companies.length > 0 && (
                <div className="flex items-start gap-2">
                  <Building2 className="mt-0.5 h-3.5 w-3.5 text-ink-faint" />
                  <div>
                    <p className="text-[11px] text-ink-faint">目标公司</p>
                    <p className="text-[13px]">{data.target_companies.join("、")}</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 text-[13px] font-medium text-ink-soft">{label}</span>
      <span className="text-[13px]">{value || <span className="text-ink-faint">暂未设置</span>}</span>
    </div>
  )
}

function EditRow({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 shrink-0 text-[13px] font-medium text-ink-soft">{label}</span>
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="h-8 text-[13px]" />
    </div>
  )
}

function IconField({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-3.5 w-3.5 text-ink-faint" />
      <div>
        <p className="text-[11px] text-ink-faint">{label}</p>
        <p className="text-[13px]">{value || <span className="text-ink-faint">暂未设置</span>}</p>
      </div>
    </div>
  )
}
