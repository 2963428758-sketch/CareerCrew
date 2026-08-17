import { useEffect, useRef, useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorCard } from "@/components/data/shared"
import { useChatStore } from "@/store/chatStore"
import { apiFetch, getAuthSnapshot } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

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
        if (!r.ok) throw new Error(await apiErrorText(r, "加载画像失败"))
        return r.json()
      })
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(networkErrorText(e, "网络连接失败，请检查网络后重试")) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [url])
  return { data, loading, error }
}

const toList = (v: string) => (v ? v.split(/[、,，\s]+/).filter(Boolean) : [])
const toInt = (v: string) => (v.trim() ? parseInt(v) : null)

/** 能力画像字段（一行一个，无提示文案，失焦自动保存） */
const PROFILE_FIELDS: { key: string; label: string }[] = [
  { key: "profile.direction", label: "方向" },
  { key: "profile.level", label: "级别" },
  { key: "profile.experience_years", label: "经验年限" },
  { key: "profile.skills", label: "技能" },
]

/** 求职方向字段 */
const DIRECTION_FIELDS: { key: string; label: string }[] = [
  { key: "preferences.salary_min", label: "薪资下限(K)" },
  { key: "preferences.salary_max", label: "薪资上限(K)" },
  { key: "preferences.city", label: "期望城市" },
  { key: "preferences.work_mode", label: "工作模式" },
  { key: "target_companies", label: "目标公司" },
]

/**
 * 能力画像 / 求职方向：标题在框外，内容在圆润框内，每一行横线隔开；
 * 每个字段一个输入框（无边框、无占位提示），失焦 / Enter 自动保存，允许为空。
 */
export function ProfilePanel() {
  const nonce = useChatStore((s) => s.profileNonce)
  const url = `/api/profile?v=${nonce}`
  const { data, loading, error } = useFetch<ProfileData>(url)
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  /** 保存反馈（挂在对应大类标题右侧，不出现在页面最上方） */
  const [feedback, setFeedback] = useState<{ section: "profile" | "direction"; kind: "ok" | "error"; text: string } | null>(null)
  /** 最近一次已保存的字段快照：失焦时值没变就不重复请求 */
  const savedRef = useRef<Record<string, unknown>>({})

  const buildSection = (section: "profile" | "direction"): Record<string, unknown> => {
    if (section === "profile") {
      return {
        "profile.direction": form["profile.direction"] || "",
        "profile.level": form["profile.level"] || "",
        "profile.experience_years": toInt(form["profile.experience_years"] || ""),
        "profile.skills": toList(form["profile.skills"] || ""),
      }
    }
    return {
      "preferences.salary_min": toInt(form["preferences.salary_min"] || ""),
      "preferences.salary_max": toInt(form["preferences.salary_max"] || ""),
      "preferences.city": toList(form["preferences.city"] || ""),
      "preferences.work_mode": form["preferences.work_mode"] || "",
      "target_companies": toList(form["target_companies"] || ""),
    }
  }

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
      // 已保存快照从 data 直接构建（此时 form 还是旧状态，不能用 buildSection）
      savedRef.current = {
        "profile.direction": p.direction || "",
        "profile.level": p.level || "",
        "profile.experience_years": p.experience_years ?? null,
        "profile.skills": p.skills || [],
        "preferences.salary_min": pref.salary_min ?? null,
        "preferences.salary_max": pref.salary_max ?? null,
        "preferences.city": pref.city || [],
        "preferences.work_mode": pref.work_mode || "",
        "target_companies": data.target_companies || [],
      }
    }
  }, [data])

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!data) return null

  const putFields = async (section: "profile" | "direction", fields: Record<string, unknown>, okText: string) => {
    setSaving(true)
    setFeedback(null)
    try {
      const resp = await apiFetch(`/api/profile?user_id=${getAuthSnapshot().user?.id ?? "u_001"}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields }),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "保存画像失败"))
      useChatStore.getState().bumpProfileNonce()
      savedRef.current = { ...savedRef.current, ...fields }
      setFeedback({ section, kind: "ok", text: okText })
      setTimeout(() => setFeedback(null), 3000)
    } catch (e) {
      setFeedback({ section, kind: "error", text: `保存失败：${networkErrorText(e, "请稍后重试")}` })
    } finally {
      setSaving(false)
    }
  }

  /** 失焦 / Enter 自动保存对应大类（值与上次保存一致时跳过） */
  const saveSection = (section: "profile" | "direction") => {
    const fields = buildSection(section)
    const same = Object.entries(fields).every(([k, v]) => JSON.stringify(savedRef.current[k]) === JSON.stringify(v))
    if (same) return
    void putFields(section, fields, "✓ 已保存")
  }

  const renderSection = (title: string, fields: typeof PROFILE_FIELDS, section: "profile" | "direction") => (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[13px] font-medium text-ink">{title}</h3>
        {feedback?.section === section && (
          <p className={feedback.kind === "ok" ? "text-[12px] font-medium text-green-600" : "text-[12px] font-medium text-destructive"}>
            {feedback.text}
          </p>
        )}
      </div>
      <div className="overflow-hidden rounded-[12px] border border-[var(--border-soft)] bg-workspace">
        {fields.map((f) => (
          <div
            key={f.key}
            className="flex items-center gap-3 border-b border-[var(--border-soft)] px-3.5 py-2.5 last:border-0"
          >
            <span className="w-24 shrink-0 text-[13px] font-medium text-ink-soft">{f.label}</span>
            <input
              value={form[f.key] || ""}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              onBlur={() => saveSection(section)}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur() }}
              disabled={saving}
              className="h-8 flex-1 border-0 bg-transparent px-0 text-[13px] text-ink outline-none disabled:opacity-60"
            />
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <div className="space-y-5">
      {renderSection("能力画像", PROFILE_FIELDS, "profile")}
      {renderSection("求职方向", DIRECTION_FIELDS, "direction")}
    </div>
  )
}
