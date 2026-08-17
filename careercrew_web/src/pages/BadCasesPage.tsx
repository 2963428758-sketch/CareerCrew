import { useEffect, useMemo, useState } from "react"
import { ArrowRight, RefreshCw } from "lucide-react"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { fetchBadCases, REVIEW_STATUS_LABELS, type BadCase, type ReviewStatus } from "@/lib/quality"

const REASON_LABELS: Record<string, string> = {
  incorrect: "回答错误", not_relevant: "答非所问", incomplete: "回答不完整", too_verbose: "过于冗长",
  unclear: "表述不清", instruction_failure: "未遵循指令", tool_failure: "工具失败",
  citation_failure: "引用失败", other: "其他",
}

const STATUS_FILTERS: (ReviewStatus | "all")[] = ["all", "new", "triaged", "fixed", "ignored", "promoted_to_eval"]

const fmtTime = (value: string) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false })
}

export default function BadCasesPage() {
  const [cases, setCases] = useState<BadCase[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<ReviewStatus | "all">("all")

  const load = async () => {
    setError(null)
    setCases(null)
    try {
      setCases(await fetchBadCases())
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    }
  }
  useEffect(() => { void load() }, [])

  const filtered = useMemo(
    () => (cases ?? []).filter((row) => filter === "all" || row.review_status === filter),
    [cases, filter]
  )
  const counts = useMemo(() => {
    const map = new Map<ReviewStatus, number>()
    for (const row of cases ?? []) {
      const status: ReviewStatus = row.review_status ?? "new"
      map.set(status, (map.get(status) ?? 0) + 1)
    }
    return map
  }, [cases])

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        parent="CareerCrew"
        title="坏例管理"
        subtitle="负反馈归因与处理"
        actions={
          <Button variant="ghost" size="icon" onClick={() => void load()} aria-label="刷新">
            <RefreshCw className="h-4 w-4" strokeWidth={1.7} />
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {STATUS_FILTERS.map((status) => (
            <button
              key={status}
              onClick={() => setFilter(status)}
              className={cn(
                "rounded-[7px] border border-[var(--border-soft)] px-2.5 py-1 text-[12.5px] transition-colors",
                filter === status ? "bg-button-ink text-button-onink" : "text-ink-soft hover:bg-[var(--hover)]"
              )}
            >
              {status === "all" ? "全部" : REVIEW_STATUS_LABELS[status]}
              <span className="ml-1 opacity-70">{status === "all" ? cases?.length ?? 0 : counts.get(status) ?? 0}</span>
            </button>
          ))}
        </div>
        {error && <div className="mb-3 rounded-[10px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">{error}</div>}
        {!cases && !error && <div className="text-[13px] text-ink-faint">加载中…</div>}
        {cases && filtered.length === 0 && (
          <div className="rounded-[10px] border border-dashed border-[var(--border-soft)] px-4 py-10 text-center text-[13px] text-ink-faint">
            当前筛选下没有坏例
          </div>
        )}
        <div className="flex flex-col gap-2">
          {filtered.map((row) => (
            <Card key={row.feedback_id}>
              <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-1.5 p-3.5">
                <Badge variant={row.review_status === "new" || !row.review_status ? "destructive" : "secondary"}>
                  {REVIEW_STATUS_LABELS[row.review_status ?? "new"]}
                </Badge>
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                  {REASON_LABELS[row.reason] ?? row.reason}
                  {row.root_cause && <span className="ml-2 text-[12px] text-ink-faint">根因：{row.root_cause}</span>}
                </span>
                <span className="shrink-0 text-[12px] text-ink-faint">
                  {row.module} · {row.agent_id} · v{row.prompt_version}
                </span>
                {row.snapshot_available && (
                  <Badge variant="outline" className="border-primary/30 text-primary">可查看上下文</Badge>
                )}
                <span className="shrink-0 text-[12px] text-ink-faint">{fmtTime(row.updated_at)}</span>
                <a
                  href={`/quality/bad-cases/${row.feedback_id}`}
                  className="inline-flex items-center gap-1 rounded-[7px] px-2 py-1 text-[12.5px] text-primary transition-colors hover:bg-primary/5"
                >
                  处理 <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.7} />
                </a>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}