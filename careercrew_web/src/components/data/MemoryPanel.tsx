import { useCallback, useEffect, useState } from "react"
import { Check, Clock3, Edit3, EyeOff, GitMerge, History, Save, Search, Trash2, X } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { EmptyCard, ErrorCard } from "@/components/data/shared"
import { Tooltip } from "@/components/ui/tooltip"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

interface MemoryItem {
  kind: "fact" | "event"
  id: string
  type: string
  ts?: string
  content?: string | Record<string, unknown>
  name?: string
  description?: string
  source?: string
  confidence?: number
  version?: number
  row_version?: number
  status?: string
  display_text?: string
  category?: string
  memory_type?: string
  parentId?: string | null
  thread_id?: string
}

interface MemoryPage {
  items: MemoryItem[]
  next_cursor: string | null
  total: number
}

const typeColors: Record<string, string> = {
  interview_qa: "#BE185D", job_match: "#0D9488", application: "#D97706",
  offer: "#16A34A", review: "#2563EB", note: "#78716C", profile: "#0D9488",
  preference: "#D97706", target_company: "#7C3AED", mastery: "#BE185D",
}

const MEMORY_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const STATUS_LABELS: Record<string, string> = {
  active: "当前",
  ignored: "已忽略",
  expired: "已过期",
  superseded: "已替代",
  deleted: "已删除",
}

const normalizeMemoryItem = (item: MemoryItem): MemoryItem => ({
  ...item,
  kind: item.kind || (item.memory_type === "semantic" ? "fact" : "event"),
  type: item.type || item.category || item.memory_type || "memory",
  version: item.version ?? item.row_version,
  description: item.description || item.display_text,
  content: item.content ?? item.display_text,
})

const isGovernedMemory = (item: MemoryItem) =>
  MEMORY_ID_RE.test(item.id) && Number.isInteger(item.version) && (item.version ?? 0) > 0

/** 长期记忆管理：当前事实和关键事件分开显示，按需展开而不是渲染聊天历史。 */
export function MemoryPanel() {
  const [items, setItems] = useState<MemoryItem[] | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  const [kind, setKind] = useState<"" | "fact" | "event">("")
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState("")
  const [deleting, setDeleting] = useState<string>("")
  const [includeInactive, setIncludeInactive] = useState(false)

  const load = useCallback(async (reset: boolean, requestedCursor: string | null = null) => {
    if (reset) setLoading(true)
    else setLoadingMore(true)
    setError("")
    try {
      const params = new URLSearchParams({ limit: "20" })
      if (kind) params.set("kind", kind)
      if (query.trim()) params.set("q", query.trim())
      if (includeInactive) params.set("status", "all")
      if (requestedCursor) params.set("cursor", requestedCursor)
      const resp = await apiFetch(`/api/memory/records?${params.toString()}`)
      if (!resp.ok) throw new Error(await apiErrorText(resp, "加载记忆数据失败"))
      const body = await resp.text()
      if (body.trimStart().startsWith("<")) {
        throw new Error("记忆服务返回了网页，请刷新页面；若仍存在，请重启 API 服务。")
      }
      const page = JSON.parse(body) as MemoryPage
      const normalized = page.items.map(normalizeMemoryItem)
      setItems((previous) => reset ? normalized : [...(previous ?? []), ...normalized])
      setCursor(page.next_cursor)
      setTotal(page.total)
    } catch (e) {
      setError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
    } finally {
      if (reset) setLoading(false)
      else setLoadingMore(false)
    }
  }, [includeInactive, kind, query])

  useEffect(() => { void load(true) }, [load])

  const remove = async (item: MemoryItem) => {
    setDeleting(item.id)
    try {
      const params = new URLSearchParams({ kind: item.kind })
      // 新 memory_records 使用 UUID；旧兼容行仍沿用 name / entry_id。
      if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(item.id)) params.set("record_id", item.id)
      else if (item.kind === "fact") params.set("name", item.id)
      else params.set("entry_id", item.id)
      const resp = await apiFetch(`/api/memory?${params.toString()}`, { method: "DELETE" })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "删除记忆失败"))
      await load(true)
    } catch (e) {
      setError(networkErrorText(e, "删除失败，请稍后重试"))
    } finally {
      setDeleting("")
    }
  }

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />

  const rows = items ?? []
  const facts = rows.filter((item) => item.kind === "fact")
  const events = rows.filter((item) => item.kind === "event")
  return (
    <div className="space-y-5">
      <div className="rounded-[12px] border border-[var(--border-soft)] bg-workspace p-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <label className="flex min-h-11 flex-1 items-center gap-2 rounded-[8px] border border-[var(--border-soft)] bg-surface px-3 text-ink-soft focus-within:ring-2 focus-within:ring-primary/30">
            <Search className="h-4 w-4" aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
              if (event.key === "Enter") void load(true)
            }} className="min-w-0 flex-1 bg-transparent text-[13px] outline-none" placeholder="搜索事实、公司或事件" aria-label="搜索记忆" />
          </label>
          <button onClick={() => void load(true)} className="min-h-11 rounded-[8px] bg-button-ink px-4 text-[13px] font-medium text-workspace transition-opacity hover:opacity-90">搜索</button>
        </div>
        <div className="mt-2 flex gap-2" role="group" aria-label="记忆类型筛选">
          {([ ["", "全部"], ["fact", "事实"], ["event", "事件"] ] as const).map(([value, label]) => (
            <button key={label} onClick={() => setKind(value)} aria-pressed={kind === value} className={`min-h-9 rounded-full px-3 text-[12px] transition-colors ${kind === value ? "bg-primary/10 font-medium text-primary" : "text-ink-soft hover:bg-[var(--hover)]"}`}>{label}</button>
          ))}
          <button
            type="button"
            onClick={() => setIncludeInactive((value) => !value)}
            aria-pressed={includeInactive}
            className="ml-auto min-h-9 rounded-full px-2.5 text-[11px] text-ink-faint transition-colors hover:bg-[var(--hover)] hover:text-ink"
          >
            {includeInactive ? "只看当前" : "查看已忽略/过期"}
          </button>
          <span className="self-center text-[11px] text-ink-faint">共 {total} 条</span>
        </div>
      </div>

      {rows.length === 0 ? (
        <EmptyCard text="暂无长期记忆。普通聊天不会出现在这里；可在「记忆设置」开启或明确要求保存。" />
      ) : (
        <>
          {facts.length > 0 && <MemoryGroup title="当前事实" hint="会随用户新的明确表达更新" items={facts} candidates={rows} deleting={deleting} onDelete={remove} onChanged={async () => { await load(true) }} />}
          {events.length > 0 && <MemoryGroup title="关键事件" hint="投递、面试、Offer 与复盘等可跨会话使用的节点" items={events} candidates={rows} deleting={deleting} onDelete={remove} onChanged={async () => { await load(true) }} />}
        </>
      )}

      {cursor && <button onClick={() => void load(false, cursor)} disabled={loadingMore} aria-label="加载更多记忆" className="min-h-11 w-full rounded-[8px] border border-[var(--border-soft)] text-[13px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:cursor-not-allowed disabled:opacity-50">{loadingMore ? "正在加载…" : "加载更多"}</button>}
    </div>
  )
}

function MemoryGroup({ title, hint, items, candidates, deleting, onDelete, onChanged }: { title: string; hint: string; items: MemoryItem[]; candidates: MemoryItem[]; deleting: string; onDelete: (item: MemoryItem) => void; onChanged: () => Promise<void> }) {
  return <section aria-labelledby={`memory-${title}`}>
    <div className="mb-2 flex items-baseline justify-between gap-3"><div><h3 id={`memory-${title}`} className="text-[14px] font-semibold text-ink">{title}</h3><p className="mt-0.5 text-[12px] text-ink-faint">{hint}</p></div><span className="text-[11px] text-ink-faint">{items.length} 条</span></div>
    <div className="space-y-2">{items.map((item) => <MemoryCard key={`${item.kind}-${item.id}`} item={item} candidates={candidates} deleting={deleting} onDelete={onDelete} onChanged={onChanged} />)}</div>
  </section>
}

function MemoryCard({ item, candidates, deleting, onDelete, onChanged }: { item: MemoryItem; candidates: MemoryItem[]; deleting: string; onDelete: (item: MemoryItem) => void; onChanged: () => Promise<void> }) {
  const color = typeColors[item.type] || "#78716C"
  const governed = isGovernedMemory(item)
  const candidatesForMerge = candidates.filter((candidate) => candidate.id !== item.id && isGovernedMemory(candidate))
  const [busy, setBusy] = useState("")
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.description || item.display_text || "")
  const [mergeTarget, setMergeTarget] = useState(candidatesForMerge[0]?.id || "")
  const [history, setHistory] = useState<Array<{ action?: string; reason?: string; created_at?: string }>>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [feedback, setFeedback] = useState("")
  const rowVersion = item.version ?? item.row_version

  const applyAction = async (action: "confirm" | "edit" | "ignore" | "expire", extra: Record<string, unknown> = {}) => {
    if (!rowVersion) return
    setBusy(action)
    setFeedback("")
    try {
      const resp = await apiFetch(`/api/memory/records/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, row_version: rowVersion, ...extra }),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "更新记忆失败"))
      setEditing(false)
      await onChanged()
    } catch (e) {
      setFeedback(networkErrorText(e, "更新失败，请稍后重试"))
    } finally {
      setBusy("")
    }
  }

  const loadHistory = async () => {
    if (!governed) return
    if (historyOpen) {
      setHistoryOpen(false)
      return
    }
    setBusy("history")
    setFeedback("")
    try {
      const resp = await apiFetch(`/api/memory/records/${encodeURIComponent(item.id)}/history`)
      if (!resp.ok) throw new Error(await apiErrorText(resp, "加载变更历史失败"))
      const body = await resp.json() as { events?: Array<{ action?: string; reason?: string; created_at?: string }> }
      setHistory(body.events || [])
      setHistoryOpen(true)
    } catch (e) {
      setFeedback(networkErrorText(e, "历史加载失败，请稍后重试"))
    } finally {
      setBusy("")
    }
  }

  const merge = async () => {
    const target = candidatesForMerge.find((candidate) => candidate.id === mergeTarget)
    if (!target || !rowVersion || !target.version) return
    setBusy("merge")
    setFeedback("")
    try {
      const resp = await apiFetch(`/api/memory/records/${encodeURIComponent(item.id)}/merge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          other_memory_id: target.id,
          row_version: rowVersion,
          other_row_version: target.version,
          reason: "用户在记忆面板合并",
        }),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "合并记忆失败"))
      await onChanged()
    } catch (e) {
      setFeedback(networkErrorText(e, "合并失败，请稍后重试"))
    } finally {
      setBusy("")
    }
  }

  return <Card><CardContent className="p-3"><div className="flex items-start gap-2"><span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Badge variant="secondary" className="text-[11px]">{item.type}</Badge>{item.status && item.status !== "active" && <Badge variant="outline" className="text-[11px]">{STATUS_LABELS[item.status] || item.status}</Badge>}{item.ts && <span className="text-[11px] text-ink-faint">{item.ts.slice(0, 19).replace("T", " ")}</span>}{item.source && <span className="text-[11px] text-ink-faint">来源：{item.source}</span>}</div>{item.description && <p className="mt-1 text-[12px] text-ink-faint">{item.description}</p>}<details className="mt-2"><summary className="cursor-pointer text-[12px] font-medium text-primary">查看内容与来源</summary><div className="mt-2"><MemoryContent content={item.content} /></div></details>{governed && <div className="mt-3 space-y-2 border-t border-[var(--border-soft)] pt-2.5"><div className="flex flex-wrap gap-1.5"><button type="button" onClick={() => void applyAction("confirm")} disabled={!!busy} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] bg-primary/10 px-2.5 text-[12px] font-medium text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-50"><Check className="h-3.5 w-3.5" />确认正确</button><button type="button" onClick={() => { setDraft(item.description || item.display_text || ""); setEditing((value) => !value) }} disabled={!!busy} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:opacity-50"><Edit3 className="h-3.5 w-3.5" />修改</button><button type="button" onClick={() => void applyAction("ignore")} disabled={!!busy} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:opacity-50"><EyeOffIcon />暂时忽略</button><button type="button" onClick={() => void applyAction("expire")} disabled={!!busy} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:opacity-50"><Clock3 className="h-3.5 w-3.5" />标记过期</button><button type="button" onClick={() => void loadHistory()} disabled={!!busy && busy !== "history"} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:opacity-50"><History className="h-3.5 w-3.5" />{busy === "history" ? "加载中…" : historyOpen ? "收起历史" : "查看变更历史"}</button></div>{editing && <div className="space-y-2 rounded-[8px] bg-surface-2 p-2.5"><label className="block text-[12px] font-medium text-ink-soft" htmlFor={`memory-edit-${item.id}`}>修改后的记忆</label><textarea id={`memory-edit-${item.id}`} value={draft} onChange={(event) => setDraft(event.target.value)} rows={3} className="w-full resize-y rounded-[7px] border border-input bg-workspace p-2 text-[13px] leading-relaxed text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring/40" /><div className="flex gap-1.5"><button type="button" onClick={() => void applyAction("edit", { display_text: draft })} disabled={!!busy || !draft.trim()} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] bg-button-ink px-2.5 text-[12px] text-button-onink disabled:opacity-50"><Save className="h-3.5 w-3.5" />保存修改</button><button type="button" onClick={() => setEditing(false)} disabled={!!busy} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft disabled:opacity-50"><X className="h-3.5 w-3.5" />取消</button></div></div>}{candidatesForMerge.length > 0 && <div className="flex flex-wrap items-center gap-1.5"><label className="text-[12px] text-ink-faint" htmlFor={`memory-merge-${item.id}`}>合并目标</label><select id={`memory-merge-${item.id}`} aria-label="合并目标" value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)} disabled={!!busy} className="min-h-11 min-w-0 flex-1 rounded-[7px] border border-input bg-workspace px-2 text-[12px] text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring/40">{candidatesForMerge.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.description || candidate.display_text || candidate.id}</option>)}</select><button type="button" onClick={() => void merge()} disabled={!!busy || !mergeTarget} className="inline-flex min-h-11 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:opacity-50"><GitMerge className="h-3.5 w-3.5" />合并</button></div>}{historyOpen && <div className="rounded-[8px] bg-surface-2 p-2.5"><p className="text-[12px] font-medium text-ink-soft">变更历史</p>{history.length === 0 ? <p className="mt-1 text-[12px] text-ink-faint">暂无变更记录</p> : <ol className="mt-1.5 space-y-1.5">{history.map((event, index) => <li key={`${event.created_at || "event"}-${index}`} className="text-[12px] text-ink-faint">{event.created_at ? event.created_at.slice(0, 19).replace("T", " ") : ""} · {event.action === "edit" ? "修改" : event.action === "confirm" ? "确认正确" : event.action === "ignore" ? "暂时忽略" : event.action === "expire" ? "标记过期" : event.action || "变更"}{event.reason ? ` · ${event.reason}` : ""}</li>)}</ol>}</div>}{feedback && <p role="alert" className="text-[12px] font-medium text-destructive">{feedback}</p>}</div>}</div><Tooltip label="删除这条长期记忆"><button onClick={() => onDelete(item)} disabled={deleting === item.id || !!busy} aria-label={`删除记忆 ${item.type}`} className="-mt-1 flex min-h-11 min-w-11 items-center justify-center rounded-[6px] text-ink-faint transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"><Trash2 className="h-4 w-4" /></button></Tooltip></div></CardContent></Card>
}

function EyeOffIcon() {
  return <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
}

function MemoryContent({ content }: { content?: string | Record<string, unknown> }) {
  if (!content) return <p className="text-[13px] text-ink-faint">（空）</p>
  if (typeof content === "string") return <p className="text-[13px] leading-relaxed">{content}</p>
  return <div className="space-y-1 text-[13px]">{Object.entries(content).map(([key, value]) => <p key={key}><span className="font-medium text-ink-soft">{key}：</span>{typeof value === "string" ? value : JSON.stringify(value)}</p>)}</div>
}
