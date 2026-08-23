import { useEffect, useState } from "react"
import { Search, Trash2 } from "lucide-react"
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

  const load = async (reset: boolean, requestedCursor: string | null = null) => {
    reset ? setLoading(true) : setLoadingMore(true)
    setError("")
    try {
      const params = new URLSearchParams({ limit: "20" })
      if (kind) params.set("kind", kind)
      if (query.trim()) params.set("q", query.trim())
      if (requestedCursor) params.set("cursor", requestedCursor)
      const resp = await apiFetch(`/api/memory/records?${params.toString()}`)
      if (!resp.ok) throw new Error(await apiErrorText(resp, "加载记忆数据失败"))
      const page = await resp.json() as MemoryPage
      setItems((previous) => reset ? page.items : [...(previous ?? []), ...page.items])
      setCursor(page.next_cursor)
      setTotal(page.total)
    } catch (e) {
      setError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
    } finally {
      reset ? setLoading(false) : setLoadingMore(false)
    }
  }

  useEffect(() => { void load(true) }, [kind])

  const remove = async (item: MemoryItem) => {
    setDeleting(item.id)
    try {
      const params = new URLSearchParams({ kind: item.kind })
      if (item.kind === "fact") params.set("name", item.id)
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
  if (!items || items.length === 0) {
    return <EmptyCard text="暂无长期记忆。普通聊天不会出现在这里；可在「记忆设置」开启或明确要求保存。" />
  }

  const facts = items.filter((item) => item.kind === "fact")
  const events = items.filter((item) => item.kind === "event")
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
          <span className="ml-auto self-center text-[11px] text-ink-faint">共 {total} 条</span>
        </div>
      </div>

      {facts.length > 0 && <MemoryGroup title="当前事实" hint="会随用户新的明确表达更新" items={facts} deleting={deleting} onDelete={remove} />}
      {events.length > 0 && <MemoryGroup title="关键事件" hint="投递、面试、Offer 与复盘等可跨会话使用的节点" items={events} deleting={deleting} onDelete={remove} />}

      {cursor && <button onClick={() => void load(false, cursor)} disabled={loadingMore} aria-label="加载更多记忆" className="min-h-11 w-full rounded-[8px] border border-[var(--border-soft)] text-[13px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:cursor-not-allowed disabled:opacity-50">{loadingMore ? "正在加载…" : "加载更多"}</button>}
    </div>
  )
}

function MemoryGroup({ title, hint, items, deleting, onDelete }: { title: string; hint: string; items: MemoryItem[]; deleting: string; onDelete: (item: MemoryItem) => void }) {
  return <section aria-labelledby={`memory-${title}`}>
    <div className="mb-2 flex items-baseline justify-between gap-3"><div><h3 id={`memory-${title}`} className="text-[14px] font-semibold text-ink">{title}</h3><p className="mt-0.5 text-[12px] text-ink-faint">{hint}</p></div><span className="text-[11px] text-ink-faint">{items.length} 条</span></div>
    <div className="space-y-2">{items.map((item) => <MemoryCard key={`${item.kind}-${item.id}`} item={item} deleting={deleting} onDelete={onDelete} />)}</div>
  </section>
}

function MemoryCard({ item, deleting, onDelete }: { item: MemoryItem; deleting: string; onDelete: (item: MemoryItem) => void }) {
  const color = typeColors[item.type] || "#78716C"
  return <Card><CardContent className="p-3"><div className="flex items-start gap-2"><span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Badge variant="secondary" className="text-[11px]">{item.type}</Badge>{item.ts && <span className="text-[11px] text-ink-faint">{item.ts.slice(0, 19).replace("T", " ")}</span>}{item.source && <span className="text-[11px] text-ink-faint">来源：{item.source}</span>}</div>{item.description && <p className="mt-1 text-[12px] text-ink-faint">{item.description}</p>}<details className="mt-2"><summary className="cursor-pointer text-[12px] font-medium text-primary">查看内容与来源</summary><div className="mt-2"><MemoryContent content={item.content} /></div></details></div><Tooltip label="删除这条长期记忆"><button onClick={() => onDelete(item)} disabled={deleting === item.id} aria-label={`删除记忆 ${item.type}`} className="-mt-1 flex min-h-11 min-w-11 items-center justify-center rounded-[6px] text-ink-faint transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"><Trash2 className="h-4 w-4" /></button></Tooltip></div></CardContent></Card>
}

function MemoryContent({ content }: { content?: string | Record<string, unknown> }) {
  if (!content) return <p className="text-[13px] text-ink-faint">（空）</p>
  if (typeof content === "string") return <p className="text-[13px] leading-relaxed">{content}</p>
  return <div className="space-y-1 text-[13px]">{Object.entries(content).map(([key, value]) => <p key={key}><span className="font-medium text-ink-soft">{key}：</span>{typeof value === "string" ? value : JSON.stringify(value)}</p>)}</div>
}
