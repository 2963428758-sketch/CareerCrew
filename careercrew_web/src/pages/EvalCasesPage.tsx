import { useEffect, useState } from "react"
import { Download, RefreshCw } from "lucide-react"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  approveEvalCase, exportEvalCases, fetchEvalCases, putEvalCase,
  EVAL_STATUSES, type EvalCase, type EvalStatus,
} from "@/lib/quality"

const STATUS_LABELS: Record<EvalStatus, string> = { draft: "草稿", approved: "已批准", deprecated: "已弃用" }
const fmtTime = (value?: string | null) => {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false })
}

export default function EvalCasesPage() {
  const [cases, setCases] = useState<EvalCase[] | null>(null)
  const [filter, setFilter] = useState<EvalStatus | "all">("all")
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [expected, setExpected] = useState("")
  const [rubricText, setRubricText] = useState("")

  const load = async () => {
    setError(null)
    setCases(null)
    try {
      setCases(await fetchEvalCases(filter === "all" ? undefined : filter))
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败")
    }
  }
  useEffect(() => { void load() }, [filter])

  const beginEdit = (row: EvalCase) => {
    setEditingId(row.id)
    setExpected(row.expected_behavior ?? "")
    setRubricText(JSON.stringify(row.rubric ?? {}, null, 2))
  }

  const saveEdit = async (row: EvalCase) => {
    if (editingId !== row.id) return
    setBusyId(row.id)
    try {
      let rubric: Record<string, unknown> | undefined
      try {
        const parsed: unknown = JSON.parse(rubricText)
        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("必须是 JSON 对象")
        rubric = parsed as Record<string, unknown>
      } catch (err) {
        setError(`评分细则格式无效：${err instanceof Error ? err.message : "未知错误"}`)
        setBusyId(null)
        return
      }
      await putEvalCase(row.id, { expected_behavior: expected, rubric })
      setEditingId(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setBusyId(null)
    }
  }

  const doApprove = async (row: EvalCase) => {
    setBusyId(row.id)
    try {
      await approveEvalCase(row.id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "审批失败")
    } finally {
      setBusyId(null)
    }
  }

  const doDeprecate = async (row: EvalCase) => {
    setBusyId(row.id)
    try {
      await putEvalCase(row.id, { status: "deprecated" })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "弃用失败")
    } finally {
      setBusyId(null)
    }
  }

  const doExport = async () => {
    try {
      const content = await exportEvalCases()
      const blob = new Blob([content], { type: "application/x-ndjson" })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = "eval-cases.jsonl"
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败")
    }
  }

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        parent="CareerCrew"
        title="评估集管理"
        subtitle="草稿编辑 · 审批 · 版本化导出"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => void doExport()}>
              <Download className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} /> 导出 JSONL
            </Button>
            <Button variant="ghost" size="icon" onClick={() => void load()} aria-label="刷新">
              <RefreshCw className="h-4 w-4" strokeWidth={1.7} />
            </Button>
          </>
        }
      />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {(["all", ...EVAL_STATUSES] as (EvalStatus | "all")[]).map((status) => (
            <button
              key={status}
              onClick={() => setFilter(status)}
              className={cn(
                "rounded-[7px] border border-[var(--border-soft)] px-2.5 py-1 text-[12.5px] transition-colors",
                filter === status ? "bg-button-ink text-button-onink" : "text-ink-soft hover:bg-[var(--hover)]"
              )}
            >
              {status === "all" ? "全部" : STATUS_LABELS[status]}
            </button>
          ))}
        </div>
        {error && <div className="mb-3 rounded-[10px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">{error}</div>}
        {!cases && !error && <div className="text-[13px] text-ink-faint">加载中…</div>}
        {cases && cases.length === 0 && (
          <div className="rounded-[10px] border border-dashed border-[var(--border-soft)] px-4 py-10 text-center text-[13px] text-ink-faint">
            暂无评估用例：在坏例详情中点击「转入评估集」创建草稿
          </div>
        )}
        <div className="flex flex-col gap-2">
          {cases?.map((row) => (
            <Card key={row.id}>
              <CardContent className="p-3.5">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                  <Badge variant={row.status === "draft" ? "outline" : row.status === "approved" ? "default" : "secondary"}>
                    {STATUS_LABELS[row.status]}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{row.input_text || "（空输入）"}</span>
                  <span className="shrink-0 text-[12px] text-ink-faint">{row.target_agent} · v{row.source_prompt_version ?? "?"}</span>
                  <span className="shrink-0 text-[12px] text-ink-faint">{fmtTime(row.created_at)}</span>
                  {row.status === "draft" && (
                    <div className="flex shrink-0 gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => beginEdit(row)}>编辑</Button>
                      <Button size="sm" disabled={busyId === row.id} onClick={() => void doApprove(row)}>批准</Button>
                    </div>
                  )}
                  {row.status === "approved" && (
                    <Button size="sm" variant="ghost" disabled={busyId === row.id} onClick={() => void doDeprecate(row)}>弃用</Button>
                  )}
                </div>
                {editingId === row.id && (
                  <div className="mt-3 flex flex-col gap-2 border-t border-[var(--border-soft)] pt-3">
                    <div>
                      <div className="mb-1 text-[11px] text-ink-faint">期望行为（批准必填）</div>
                      <textarea
                        value={expected}
                        onChange={(event) => setExpected(event.target.value)}
                        rows={2}
                        className="w-full rounded-[7px] border border-input bg-card px-2.5 py-1.5 text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                        placeholder="例如：工具失败时必须提供降级方案"
                      />
                    </div>
                    <div>
                      <div className="mb-1 text-[11px] text-ink-faint">评分细则（JSON，批准必填）</div>
                      <textarea
                        value={rubricText}
                        onChange={(event) => setRubricText(event.target.value)}
                        rows={4}
                        className="w-full rounded-[7px] border border-input bg-card px-2.5 py-1.5 font-mono text-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                        placeholder='{"must_include": ["降级方案"]}'
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" disabled={busyId === row.id} onClick={() => void saveEdit(row)}>保存</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>取消</Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}