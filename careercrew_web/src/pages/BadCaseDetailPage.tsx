import { useEffect, useState } from "react"
import { useLocation } from "react-router-dom"
import { ArrowLeft, Eye, ShieldCheck } from "lucide-react"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  fetchBadCase, fetchReview, fetchSnapshot, putReview, promoteToEval,
  REVIEW_ROOT_CAUSES, REVIEW_STATUSES, REVIEW_STATUS_LABELS, ROOT_CAUSE_LABELS,
  type BadCase, type ReviewRow, type ReviewRootCause, type ReviewStatus, type SnapshotRow,
} from "@/lib/quality"

const REASON_LABELS: Record<string, string> = {
  incorrect: "回答错误", not_relevant: "答非所问", incomplete: "回答不完整", too_verbose: "过于冗长",
  unclear: "表述不清", instruction_failure: "未遵循指令", tool_failure: "工具失败",
  citation_failure: "引用失败", other: "其他",
}

const fmtTime = (value?: string | null) => {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false })
}

function Field({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-ink-faint">{label}</span>
      <span className={cn("text-[13px] text-ink", mono && "font-mono text-[12px]")}>{children}</span>
    </div>
  )
}

export default function BadCaseDetailPage() {
  const feedbackId = useLocation().pathname.split("/").filter(Boolean).pop() ?? ""
  const [case_, setCase] = useState<BadCase | null>(null)
  const [review, setReview] = useState<ReviewRow | null>(null)
  const [snapshot, setSnapshot] = useState<SnapshotRow | null>(null)
  const [snapshotError, setSnapshotError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const [rootCause, setRootCause] = useState<ReviewRootCause | "">("")
  const [status, setStatus] = useState<ReviewStatus>("new")
  const [note, setNote] = useState("")
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let disposed = false
    const load = async () => {
      try {
        const [badCase, reviewRow] = await Promise.all([fetchBadCase(feedbackId), fetchReview(feedbackId)])
        if (disposed) return
        setCase(badCase)
        setReview(reviewRow)
        setRootCause(reviewRow?.root_cause ?? "")
        setStatus(reviewRow?.review_status ?? "new")
        setNote(reviewRow?.reviewer_note ?? "")
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : "加载失败")
      } finally {
        if (!disposed) setLoaded(true)
      }
    }
    void load()
    return () => { disposed = true }
  }, [feedbackId])

  const viewSnapshot = async () => {
    setSnapshotError(null)
    try {
      setSnapshot(await fetchSnapshot(feedbackId))
    } catch (err) {
      setSnapshotError(err instanceof Error ? err.message : "快照加载失败")
    }
  }

  const saveReview = async (nextStatus: ReviewStatus, nextCause?: ReviewRootCause | "") => {
    setBusy("save")
    try {
      const row = await putReview(feedbackId, {
        status: nextStatus,
        root_cause: nextCause === undefined ? (rootCause || null) : (nextCause || null),
        note,
      })
      setReview(row)
      setStatus(row.review_status)
      setRootCause(row.root_cause ?? "")
      setNote(row.reviewer_note ?? "")
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setBusy(null)
    }
  }

  const doPromote = async () => {
    setBusy("promote")
    try {
      await promoteToEval(feedbackId)
      const [badCase, reviewRow] = await Promise.all([fetchBadCase(feedbackId), fetchReview(feedbackId)])
      setCase(badCase)
      setReview(reviewRow)
      setStatus(reviewRow?.review_status ?? "new")
    } catch (err) {
      setError(err instanceof Error ? err.message : "转评估失败")
    } finally {
      setBusy(null)
    }
  }

  if (!loaded) return <div className="p-6 text-[13px] text-ink-faint">加载中…</div>
  if (error && !case_) {
    return (
      <div className="p-6">
        <a href="/quality/bad-cases" className="inline-flex items-center gap-1 text-[13px] text-primary">
          <ArrowLeft className="h-4 w-4" strokeWidth={1.7} /> 返回坏例列表
        </a>
        <div className="mt-3 rounded-[10px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">{error}</div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        parent="CareerCrew"
        title="坏例详情"
        subtitle={feedbackId}
        actions={
          <a href="/quality/bad-cases" className="inline-flex items-center gap-1 text-[13px] text-primary">
            <ArrowLeft className="h-4 w-4" strokeWidth={1.7} /> 返回列表
          </a>
        }
      />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error && <div className="mb-3 rounded-[10px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">{error}</div>}
        {case_ && (
          <div className="flex flex-col gap-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2">
                  反馈元数据
                  <Badge variant={status === "new" ? "destructive" : "secondary"}>{REVIEW_STATUS_LABELS[status]}</Badge>
                  {review?.root_cause && <Badge variant="outline">根因：{ROOT_CAUSE_LABELS[review.root_cause] ?? review.root_cause}</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-x-6 gap-y-3 lg:grid-cols-4">
                <Field label="原因">{REASON_LABELS[case_.reason] ?? case_.reason}</Field>
                <Field label="模块">{case_.module}</Field>
                <Field label="Agent">{case_.agent_id}</Field>
                <Field label="模型">{case_.model}</Field>
                <Field label="Prompt 版本" mono>{case_.prompt_version}</Field>
                <Field label="Agent 版本" mono>{case_.agent_version}</Field>
                <Field label="延迟">{case_.latency_ms === null ? "—" : `${case_.latency_ms} ms`}</Field>
                <Field label="Token">{case_.input_tokens ?? 0} → {case_.output_tokens ?? 0}</Field>
                <Field label="错误类型">{case_.error_type ?? "—"}</Field>
                <Field label="错误码">{case_.error_code ?? "—"}</Field>
                <Field label="是否共享上下文">{case_.share_context ? "是" : "否"}</Field>
                <Field label="更新时间">{fmtTime(case_.updated_at)}</Field>
              </CardContent>
            </Card>

            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2"><CardTitle>人工归因（T5.4）</CardTitle></CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div>
                    <div className="mb-1 text-[11px] text-ink-faint">根因分类</div>
                    <div className="flex flex-wrap gap-1.5">
                      {REVIEW_ROOT_CAUSES.map((cause) => (
                        <button
                          key={cause}
                          onClick={() => setRootCause(rootCause === cause ? "" : cause)}
                          className={cn(
                            "rounded-[7px] border px-2 py-1 text-[12px] transition-colors",
                            rootCause === cause
                              ? "border-primary/40 bg-primary/10 text-primary"
                              : "border-[var(--border-soft)] text-ink-soft hover:bg-[var(--hover)]"
                          )}
                        >
                          {ROOT_CAUSE_LABELS[cause]}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="mb-1 text-[11px] text-ink-faint">处理状态</div>
                    <div className="flex flex-wrap gap-1.5">
                      {REVIEW_STATUSES.filter((s) => s !== "promoted_to_eval").map((next) => (
                        <button
                          key={next}
                          onClick={() => void saveReview(next)}
                          disabled={busy === "save"}
                          className={cn(
                            "rounded-[7px] border px-2 py-1 text-[12px] transition-colors",
                            status === next
                              ? "border-primary/40 bg-primary/10 text-primary"
                              : "border-[var(--border-soft)] text-ink-soft hover:bg-[var(--hover)]"
                          )}
                        >
                          {REVIEW_STATUS_LABELS[next]}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="mb-1 text-[11px] text-ink-faint">评审备注（留空则清除）</div>
                    <textarea
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      rows={3}
                      className="w-full rounded-[7px] border border-input bg-card px-2.5 py-1.5 text-[13px] placeholder:text-ink-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                      placeholder="记录修复方向、关联工单等"
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={busy === "save"} onClick={() => void saveReview(status)}>保存归因</Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === "promote" || !case_.share_context || status === "promoted_to_eval"}
                      onClick={() => void doPromote()}
                    >
                      <ShieldCheck className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} />
                      转入评估集
                    </Button>
                  </div>
                  {!case_.share_context && (
                    <div className="text-[11.5px] text-ink-faint">用户未授权共享上下文，无法转入评估集。</div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2">
                    脱敏上下文快照
                    {snapshot && <Badge variant="outline">脱敏 {snapshot.redaction_count} 处 · {snapshot.redaction_version}</Badge>}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {!snapshot && !snapshotError && (
                    <Button variant="outline" size="sm" onClick={() => void viewSnapshot()}>
                      <Eye className="mr-1 h-3.5 w-3.5" strokeWidth={1.7} /> 查看快照（记录审计）
                    </Button>
                  )}
                  {snapshotError && <div className="text-[12.5px] text-destructive">{snapshotError}</div>}
                  {snapshot && (
                    <div className="flex flex-col gap-2">
                      {snapshot.snapshot_json.messages.map((message) => (
                        <div key={message.message_id} className={cn("rounded-[8px] border border-[var(--border-soft)] p-2.5", message.role === "user" ? "bg-surface-2" : "bg-card")}>
                          <div className="mb-1 text-[10.5px] text-ink-faint">{message.role === "user" ? "用户" : "助手"} · {message.turn_id}</div>
                          <div className="whitespace-pre-wrap break-words text-[12.5px] text-ink">{message.content || "（空）"}</div>
                        </div>
                      ))}
                      <div className="text-[11px] text-ink-faint">快照有效期至 {fmtTime(snapshot.expires_at)} · 访问已写入审计日志</div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}