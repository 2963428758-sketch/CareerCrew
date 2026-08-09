import { useEffect, useState } from "react"
import { Database, User, Brain, Activity, Building2, Wallet, MapPin, Pencil, Check, X } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useChatStore } from "@/store/chatStore"

export default function DataPage() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-16 shrink-0 items-center border-b px-6">
        <div>
          <h1 className="font-display text-xl font-semibold">数据看板</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">用户画像、情景记忆与调用轨迹</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-4xl">
          <Tabs defaultValue="profile">
            <TabsList>
              <TabsTrigger value="profile" className="gap-1.5"><User className="h-3 w-3" />画像</TabsTrigger>
              <TabsTrigger value="memory" className="gap-1.5"><Brain className="h-3 w-3" />记忆</TabsTrigger>
              <TabsTrigger value="traces" className="gap-1.5"><Activity className="h-3 w-3" />轨迹</TabsTrigger>
            </TabsList>
            <TabsContent value="profile"><ProfilePanel /></TabsContent>
            <TabsContent value="memory"><MemoryPanel /></TabsContent>
            <TabsContent value="traces"><TracesPanel /></TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}

function useFetch<T>(url: string) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [url])
  return { data, loading, error }
}

// ── 画像面板（可编辑）──

interface ProfileData {
  user_id?: string
  profile?: { skills?: string[]; direction?: string; level?: string; experience_years?: number | null }
  target_companies?: string[]
  preferences?: { salary_min?: number | null; salary_max?: number | null; city?: string[]; work_mode?: string }
}

function ProfilePanel() {
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
      const resp = await fetch("/api/profile?user_id=u_001", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
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
          <CardTitle className="text-sm font-semibold">能力画像</CardTitle>
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
          <div className="px-6 pb-2">
            {saveSuccess && <p className="text-xs font-medium text-green-600">✓ 已保存</p>}
            {saveError && <p className="text-xs font-medium text-destructive">保存失败：{saveError}</p>}
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
                <span className="w-16 shrink-0 pt-0.5 text-sm font-medium text-muted-foreground">技能</span>
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
                  {p.skills && p.skills.length > 0
                    ? p.skills.map((s, i) => (
                      <span key={s}>
                        {i > 0 && <span className="text-muted-foreground/40">·</span>}
                        {s}
                      </span>
                    ))
                    : <span className="text-muted-foreground">暂无</span>}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-sm font-semibold">求职偏好</CardTitle></CardHeader>
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
                  <Building2 className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" />
                  <div>
                    <p className="text-[11px] text-muted-foreground">目标公司</p>
                    <p className="text-sm">{data.target_companies.join("、")}</p>
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
      <span className="w-16 shrink-0 text-sm font-medium text-muted-foreground">{label}</span>
      <span className="text-sm">{value || <span className="text-muted-foreground">暂未设置</span>}</span>
    </div>
  )
}

function EditRow({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 shrink-0 text-sm font-medium text-muted-foreground">{label}</span>
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="h-8 text-sm" />
    </div>
  )
}

function IconField({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      <div>
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <p className="text-sm">{value || <span className="text-muted-foreground">暂未设置</span>}</p>
      </div>
    </div>
  )
}

// ── 记忆面板 ──

interface MemoryEntry {
  id?: string
  type?: string
  ts?: string
  content?: string | Record<string, unknown>
  parentId?: string | null
}

function MemoryPanel() {
  const { data, loading, error } = useFetch<MemoryEntry[]>("/api/memory")
  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!data || data.length === 0) return <EmptyCard text="暂无情景记忆数据" />

  const typeColors: Record<string, string> = {
    session_start: "#64748B",
    interview_qa: "#BE185D",
    job_match: "#0D9488",
    application: "#D97706",
    offer: "#16A34A",
    note: "#78716C",
  }

  return (
    <div className="space-y-2">
      {data.map((entry, i) => {
        const type = entry.type || "unknown"
        const color = typeColors[type] || "#78716C"
        return (
          <Card key={entry.id || i}>
            <CardContent className="p-3">
              <div className="mb-1.5 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                <Badge variant="secondary" className="text-[11px]">{type}</Badge>
                {entry.ts && <span className="text-[11px] text-muted-foreground">{entry.ts.slice(0, 19).replace("T", " ")}</span>}
              </div>
              <MemoryContent content={entry.content} />
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function MemoryContent({ content }: { content?: string | Record<string, unknown> }) {
  if (!content) return <p className="text-sm text-muted-foreground">（空）</p>
  if (typeof content === "string") {
    return <p className="text-sm leading-relaxed">{content}</p>
  }
  const c = content as Record<string, unknown>
  if ("q" in c && "a" in c) {
    return (
      <div className="space-y-1 text-sm">
        <p><span className="font-medium text-muted-foreground">问：</span>{String(c.q)}</p>
        <p><span className="font-medium text-muted-foreground">答：</span>{String(c.a)}</p>
        {"score" in c && <p><span className="font-medium text-muted-foreground">得分：</span><span className="font-semibold text-primary">{String(c.score)}</span></p>}
      </div>
    )
  }
  return (
    <div className="space-y-0.5 text-sm">
      {Object.entries(c).map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="shrink-0 text-muted-foreground">{k}:</span>
          <span>{typeof v === "string" ? v : String(v)}</span>
        </div>
      ))}
    </div>
  )
}

// ── 轨迹面板（倒序，最新在前）──

function TracesPanel() {
  const { data, loading, error } = useFetch<Record<string, unknown>[]>("/api/traces?limit=100")
  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!data || data.length === 0) return <EmptyCard text="暂无调用轨迹" />

  const traces = [...data].reverse() // 倒序：最新在前

  return (
    <div className="space-y-1.5">
      {traces.map((trace, i) => {
        const traceType = String(trace.trace_type || trace.event || "unknown")
        const agent = trace.agent ? String(trace.agent) : null
        const ts = typeof trace.ts === "number" ? new Date(trace.ts * 1000).toLocaleString("zh-CN", { hour12: false }) : ""
        const iteration = typeof trace.iteration === "number" ? trace.iteration : null
        const toolCalls = Array.isArray(trace.tool_calls) ? (trace.tool_calls as unknown[]).map(String) : []
        const total = typeof trace.tool_calls_total === "number" ? trace.tool_calls_total : null
        const content = trace.content ? String(trace.content).slice(0, 120) : null

        return (
          <div key={i} className="rounded-md border bg-card px-3 py-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              {ts && <span className="text-muted-foreground">{ts}</span>}
              <Badge variant="outline" className="text-[11px]">{traceType}</Badge>
              {agent && <Badge variant="secondary" className="text-[11px]">{agent}</Badge>}
              {iteration !== null && <span className="text-muted-foreground">第 {iteration} 轮</span>}
              {total !== null && total > 0 && <span className="text-muted-foreground">共 {total} 次工具调用</span>}
            </div>
            {toolCalls.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {toolCalls.map((tc, j) => <Badge key={j} variant="outline" className="text-[10px] text-primary">{tc}</Badge>)}
              </div>
            )}
            {content && <p className="mt-1 text-muted-foreground">{content}{String(trace.content).length > 120 ? "…" : ""}</p>}
          </div>
        )
      })}
    </div>
  )
}

function ErrorCard({ msg }: { msg: string }) {
  return <Card className="border-destructive"><CardContent className="p-4 text-sm text-destructive">加载失败：{msg}</CardContent></Card>
}

function EmptyCard({ text }: { text: string }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-center p-12 text-muted-foreground">
        <Database className="mr-2 h-4 w-4" />{text}
      </CardContent>
    </Card>
  )
}
