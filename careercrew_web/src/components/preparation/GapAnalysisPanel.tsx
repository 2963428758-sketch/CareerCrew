import { useCallback, useEffect, useState } from "react"
import { Loader2, ScanSearch } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { networkErrorText } from "@/lib/errors"
import { createGapAnalysis, listGapAnalyses, type GapAnalysis } from "@/lib/career"

const STATUS_META: Record<string, { label: string; className: string }> = {
  matched: { label: "简历有证据", className: "text-emerald-600" },
  missing: { label: "明确缺失", className: "text-destructive" },
  not_mention: { label: "资料未提及", className: "text-amber-600" },
}

/**
 * 可解释岗位匹配：展示「岗位要求 → 简历证据 → 缺口/资料未提及」，
 * 明确区分「没有这项能力」与「简历没有提供证据」，避免匹配分数掩盖信息不足。
 */
export function GapAnalysisPanel({ opportunityId, onToast }: {
  opportunityId: string
  onToast: (msg: string) => void
}) {
  const [analyses, setAnalyses] = useState<GapAnalysis[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState("")

  const reload = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      setAnalyses(await listGapAnalyses(opportunityId))
    } catch (e) {
      setError(networkErrorText(e, "加载分析失败，请稍后重试"))
    } finally {
      setLoading(false)
    }
  }, [opportunityId])

  useEffect(() => { void reload() }, [reload])

  const run = async () => {
    if (running) return
    setRunning(true)
    setError("")
    try {
      const created = await createGapAnalysis(opportunityId, "")
      setAnalyses((prev) => [created, ...prev])
      onToast("分析完成")
    } catch (e) {
      setError(networkErrorText(e, "分析失败，请稍后重试"))
    } finally {
      setRunning(false)
    }
  }

  const latest = analyses[0]

  return (
    <div className="flex flex-col gap-2" data-testid="gap-analysis">
      <div className="flex items-center justify-between">
        <h3 className="text-[13.5px] font-[560] text-ink">可解释匹配（要求 → 证据 → 缺口）</h3>
        <Button size="sm" variant="outline" className="h-[26px] text-[12px]" disabled={running} onClick={() => void run()}>
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ScanSearch className="h-3.5 w-3.5" />}
          {running ? "分析中…" : (latest ? "重新分析" : "分析 JD 与简历")}
        </Button>
      </div>
      {loading ? (
        <p className="text-[12px] text-ink-faint">正在加载…</p>
      ) : error ? (
        <p className="text-[12px] text-destructive">{error}</p>
      ) : !latest ? (
        <p className="text-[12px] text-ink-faint">还没有分析。保存简历版本后分析更准确；未选版本时按 JD 拆解要求。</p>
      ) : (
        <>
          {latest.result.source === "llm" && (
            <Badge variant="outline" className="w-fit text-[10.5px]">AI 语义分析</Badge>
          )}
          {latest.result.source === "rules" && (
            <Badge variant="outline" className="w-fit text-[10.5px]">规则拆解（关键词比对）</Badge>
          )}
          <ul className="flex flex-col gap-1.5">
            {latest.result.requirements.map((req, i) => {
              const meta = STATUS_META[req.status] ?? {
                label: req.status,
                className: "text-ink-faint",
              }
              return (
                <li key={i} className="rounded-[8px] border border-[var(--border-soft)] bg-card px-3 py-2 text-[12.5px]">
                  <div className="flex flex-wrap items-center gap-x-2">
                    <span className="font-[560] text-ink">{req.requirement}</span>
                    <span className={meta.className}>{meta.label}</span>
                  </div>
                  {req.evidence && <p className="mt-0.5 text-ink-soft">简历证据：{req.evidence}</p>}
                  {req.note && <p className="mt-0.5 text-ink-faint">{req.note}</p>}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
