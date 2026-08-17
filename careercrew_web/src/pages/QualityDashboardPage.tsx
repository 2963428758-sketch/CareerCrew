import { useEffect, useMemo, useState } from "react"
import { Activity, AlertTriangle, Gauge, MessageSquareWarning, Timer, Cpu } from "lucide-react"
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { fetchQualityMetrics, type QualityMetrics } from "@/lib/quality"

const pct = (value: number | null | undefined) => (value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`)
const num = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? "—" : value.toFixed(digits)

function MetricCard({ label, value, hint, icon, tone }: {
  label: string; value: string; hint?: string; icon: React.ReactNode; tone?: "ok" | "warn" | "bad"
}) {
  return (
    <Card className="min-w-0">
      <CardContent className="flex items-start gap-3 p-4">
        <div className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px]",
          tone === "bad" ? "bg-destructive/10 text-destructive"
            : tone === "warn" ? "bg-amber-500/10 text-amber-600"
            : "bg-surface-2 text-ink-soft"
        )}>
          {icon}
        </div>
        <div className="min-w-0">
          <div className="text-[11px] text-ink-faint">{label}</div>
          <div className="text-[20px] font-medium leading-tight text-ink">{value}</div>
          {hint && <div className="mt-0.5 text-[11px] text-ink-faint">{hint}</div>}
        </div>
      </CardContent>
    </Card>
  )
}

function Stat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-1 text-[12.5px]", className)}>
      <span className="text-ink-soft">{label}</span>
      <span className="font-medium text-ink">{value}</span>
    </div>
  )
}

export default function QualityDashboardPage() {
  const [metrics, setMetrics] = useState<QualityMetrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let disposed = false
    const load = async () => {
      try {
        const data = await fetchQualityMetrics()
        if (!disposed) setMetrics(data)
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : "加载失败")
      } finally {
        if (!disposed) setLoading(false)
      }
    }
    void load()
    return () => { disposed = true }
  }, [])

  const distribution = useMemo(() => {
    if (!metrics) return []
    return Object.entries(metrics.negative_reason_distribution)
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => ({ reason, count, share: metrics.negative_count ? count / metrics.negative_count : 0 }))
  }, [metrics])

  const alert = metrics && metrics.unversioned_run_rate !== null && metrics.unversioned_run_rate > 0

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        parent="CareerCrew"
        title="质检看板"
        subtitle="反馈质量指标 · 仅质检员可见"
        actions={<Activity className="h-4 w-4 text-ink-faint" strokeWidth={1.7} />}
      />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading && <div className="text-[13px] text-ink-faint">加载中…</div>}
        {error && (
          <div className="rounded-[10px] border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
            {error}
            <Button variant="ghost" size="sm" className="ml-2" onClick={() => window.location.reload()}>重试</Button>
          </div>
        )}
        {metrics && (
          <div className="flex flex-col gap-4">
            {alert && (
              <div className="flex items-center gap-2 rounded-[10px] border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-[13px] text-amber-700">
                <AlertTriangle className="h-4 w-4 shrink-0" strokeWidth={1.7} />
                <span>
                  存在 <b>{metrics.unversioned_run_count}</b> 条未带版本号的运行（占比 {pct(metrics.unversioned_run_rate)}），
                  版本趋势与回归门禁不可信，请检查 Agent 调用方是否传入 prompt_version / agent_version。
                </span>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MetricCard label="有帮助率" value={pct(metrics.helpful_rate)} hint={`${metrics.feedback_count} 条已评分反馈`}
                icon={<Gauge className="h-4 w-4" strokeWidth={1.7} />}
                tone={metrics.helpful_rate !== null && metrics.helpful_rate < 0.7 ? "bad" : "ok"} />
              <MetricCard label="反馈覆盖率" value={pct(metrics.feedback_coverage)} hint={`${metrics.runs} 次运行`}
                icon={<MessageSquareWarning className="h-4 w-4" strokeWidth={1.7} />}
                tone={metrics.feedback_coverage !== null && metrics.feedback_coverage < 0.3 ? "warn" : "ok"} />
              <MetricCard label="RAG 失败占比" value={pct(metrics.rag_failure_share)} hint="引用失败 / 负反馈"
                icon={<Cpu className="h-4 w-4" strokeWidth={1.7} />}
                tone={metrics.rag_failure_share !== null && metrics.rag_failure_share > 0.5 ? "warn" : "ok"} />
              <MetricCard label="工具失败占比" value={pct(metrics.tool_failure_share)} hint="工具失败 / 负反馈"
                icon={<Activity className="h-4 w-4" strokeWidth={1.7} />}
                tone={metrics.tool_failure_share !== null && metrics.tool_failure_share > 0.5 ? "warn" : "ok"} />
              <MetricCard label="中位延迟" value={`${num(metrics.median_latency_ms)} ms`} hint={`样本 ${metrics.latency_n}`}
                icon={<Timer className="h-4 w-4" strokeWidth={1.7} />} />
              <MetricCard label="P95 延迟" value={`${num(metrics.p95_latency_ms)} ms`} hint={`样本 ${metrics.latency_n}`}
                icon={<Timer className="h-4 w-4" strokeWidth={1.7} />} />
              <MetricCard label="平均输入 Token" value={num(metrics.avg_input_tokens)} hint="含检索上下文"
                icon={<Cpu className="h-4 w-4" strokeWidth={1.7} />} />
              <MetricCard label="平均输出 Token" value={num(metrics.avg_output_tokens)} hint="模型生成"
                icon={<Cpu className="h-4 w-4" strokeWidth={1.7} />} />
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2"><CardTitle>负反馈原因分布（n={metrics.negative_count}）</CardTitle></CardHeader>
                <CardContent>
                  {distribution.length === 0 && <div className="py-3 text-[12.5px] text-ink-faint">暂无负反馈</div>}
                  <div className="flex flex-col gap-1.5">
                    {distribution.map(({ reason, count, share }) => (
                      <div key={reason} className="flex items-center gap-2">
                        <span className="w-[110px] shrink-0 truncate text-[12.5px] text-ink-soft">{reason}</span>
                        <div className="h-[14px] min-w-0 flex-1 overflow-hidden rounded-[4px] bg-surface-2">
                          <div className="h-full rounded-[4px] bg-primary/70" style={{ width: `${Math.max(share * 100, 2)}%` }} />
                        </div>
                        <span className="w-[86px] shrink-0 text-right text-[12px] text-ink-faint">{count} · {pct(share)}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2"><CardTitle>Prompt 版本趋势</CardTitle></CardHeader>
                <CardContent>
                  {metrics.helpful_rate_by_prompt_version.length === 0 && (
                    <div className="py-3 text-[12.5px] text-ink-faint">暂无已评分的带版本运行</div>
                  )}
                  <div className="flex flex-col gap-1.5">
                    {metrics.helpful_rate_by_prompt_version.map((row) => (
                      <div key={row.prompt_version} className="flex items-center gap-2">
                        <span className="w-[120px] shrink-0 truncate text-[12.5px] text-ink-soft">{row.prompt_version}</span>
                        <div className="h-[14px] min-w-0 flex-1 overflow-hidden rounded-[4px] bg-surface-2">
                          <div
                            className={cn("h-full rounded-[4px]", row.rate !== null && row.rate < 0.7 ? "bg-destructive/70" : "bg-primary/70")}
                            style={{ width: `${row.rate !== null ? Math.max(row.rate * 100, 2) : 2}%` }}
                          />
                        </div>
                        <span className="w-[110px] shrink-0 text-right text-[12px] text-ink-faint">
                          {pct(row.rate)} · n={row.feedback_count}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className="pb-1"><CardTitle>运行与反馈概况</CardTitle></CardHeader>
              <CardContent>
                <div className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
                  <Stat label="运行总数" value={String(metrics.runs)} />
                  <Stat label="已评分反馈" value={`${metrics.feedback_count}（正向 ${metrics.positive_count} / 负向 ${metrics.negative_count}）`} />
                  <Stat label="无版本运行（告警）" value={`${metrics.unversioned_run_count}（${pct(metrics.unversioned_run_rate)}）`}
                    className={alert ? "text-amber-600" : undefined} />
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}