import { useEffect, useState } from "react"
import { Trash2 } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { EmptyCard, ErrorCard } from "@/components/data/shared"
import { Tooltip } from "@/components/ui/tooltip"
import { apiFetch } from "@/lib/auth"

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

/** 记忆面板：语义事实与情景事件列表，可删除。供设置页「记忆」独立区块使用。 */
export function MemoryPanel() {
  const [data, setData] = useState<MemoryItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [deleting, setDeleting] = useState<string>("")

  const load = () => {
    setLoading(true)
    setError("")
    apiFetch("/api/memory")
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => null)
          throw new Error(body?.detail || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then((d: MemoryItem[]) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const remove = async (item: MemoryItem) => {
    setDeleting(item.id)
    try {
      const params = new URLSearchParams({ kind: item.kind })
      if (item.kind === "fact") params.set("name", item.id)
      else params.set("entry_id", item.id)
      const resp = await apiFetch(`/api/memory?${params.toString()}`, { method: "DELETE" })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDeleting("")
    }
  }

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <ErrorCard msg={error} />
  if (!data || data.length === 0) return <EmptyCard text="暂无记忆数据（记忆默认关闭，可在「记忆设置」开启）" />

  const typeColors: Record<string, string> = {
    session_start: "#64748B",
    interview_qa: "#BE185D",
    job_match: "#0D9488",
    application: "#D97706",
    offer: "#16A34A",
    review: "#2563EB",
    note: "#78716C",
    profile: "#0D9488",
    preference: "#D97706",
    target_company: "#7C3AED",
    mastery: "#BE185D",
  }

  return (
    <div className="space-y-2">
      <p className="text-[12px] text-ink-soft">语义事实（技能/偏好/目标公司）与情景事件（面试/投递/offer）。删除后不可恢复。</p>
      {data.map((entry, i) => {
        const type = entry.type || "unknown"
        const color = typeColors[type] || "#78716C"
        return (
          <Card key={`${entry.kind}-${entry.id || i}`}>
            <CardContent className="p-3">
              <div className="mb-1.5 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                <Badge variant="secondary" className="text-[11px]">
                  {entry.kind === "fact" ? "事实" : "事件"} · {type}
                </Badge>
                {entry.ts && <span className="text-[11px] text-ink-faint">{entry.ts.slice(0, 19).replace("T", " ")}</span>}
                {entry.kind === "fact" && entry.source && (
                  <span className="text-[11px] text-ink-faint">来源：{entry.source}</span>
                )}
                <Tooltip label="删除">
                  <button
                    onClick={() => remove(entry)}
                    disabled={deleting === entry.id}
                    aria-label="删除"
                    className="ml-auto rounded-[5px] p-1 text-ink-faint transition-colors duration-100 hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </Tooltip>
              </div>
              {entry.kind === "fact" && entry.description && (
                <p className="mb-1 text-[12px] text-ink-faint">{entry.description}</p>
              )}
              <MemoryContent content={entry.content} />
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function MemoryContent({ content }: { content?: string | Record<string, unknown> }) {
  if (!content) return <p className="text-[13px] text-ink-faint">（空）</p>
  if (typeof content === "string") {
    return <p className="text-[13px] leading-relaxed">{content}</p>
  }
  const c = content as Record<string, unknown>
  if ("q" in c && "a" in c) {
    return (
      <div className="space-y-1 text-[13px]">
        <p><span className="font-medium text-ink-soft">问：</span>{String(c.q)}</p>
        <p><span className="font-medium text-ink-soft">答：</span>{String(c.a)}</p>
        {"score" in c && <p><span className="font-medium text-ink-soft">得分：</span><span className="font-medium text-primary">{String(c.score)}</span></p>}
      </div>
    )
  }
  return (
    <div className="space-y-0.5 text-[13px]">
      {Object.entries(c).map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="shrink-0 text-ink-soft">{k}:</span>
          <span>{typeof v === "string" ? v : String(v)}</span>
        </div>
      ))}
    </div>
  )
}
