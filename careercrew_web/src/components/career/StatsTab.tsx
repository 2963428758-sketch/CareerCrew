import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { networkErrorText } from "@/lib/errors"
import { getGenerationMetrics, getProductFunnel, getStats, type GenerationMetrics, type JobStats, type ProductFunnel } from "@/lib/career"

export function StatsTab() {
  const [stats, setStats] = useState<JobStats | null>(null)
  const [generation, setGeneration] = useState<GenerationMetrics | null>(null)
  const [funnel, setFunnel] = useState<ProductFunnel | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    Promise.all([getStats(), getGenerationMetrics(), getProductFunnel()])
      .then(([nextStats, nextGeneration, nextFunnel]) => {
        setStats(nextStats); setGeneration(nextGeneration); setFunnel(nextFunnel)
      }).catch((e) => setError(networkErrorText(e)))
  }, [])

  if (error) return <p className="text-[12.5px] text-destructive">{error}</p>
  if (!stats) return <p className="text-[12.5px] text-ink-faint">正在统计…</p>

  const rateText = (r: { numerator: number; denominator: number; rate: number | null }) =>
    `${r.numerator}/${r.denominator}` + (r.rate !== null ? `（${(r.rate * 100).toFixed(1)}%）` : "（样本不足）")
  const eventCounts = funnel?.counts ?? {}

  return (
    <div className="flex flex-col gap-3 text-[13px]">
      <div className="grid gap-2.5 md:grid-cols-4">
        {[
          { label: "已投递", value: stats.applied },
          { label: "HR 沟通", value: stats.replies },
          { label: "进入面试", value: stats.interviewed },
          { label: "Offer", value: stats.offers },
        ].map((c) => (
          <div key={c.label} className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
            <p className="text-[11.5px] text-ink-faint">{c.label}</p>
            <p className="text-[20px] font-[600] text-ink">{c.value}</p>
          </div>
        ))}
      </div>
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">转化率（分子/分母，小样本不下结论）</p>
        <ul className="mt-1.5 flex flex-col gap-1 text-ink-soft">
          <li>回复率：{rateText(stats.reply_rate)}</li>
          <li>面试率：{rateText(stats.interview_rate)}</li>
          <li>Offer 率：{rateText(stats.offer_rate)}</li>
        </ul>
      </div>
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">来源归因（哪个渠道带来了进展）</p>
        {Object.keys(stats.by_source).length === 0 ? (
          <p className="mt-1 text-[12px] text-ink-faint">暂无数据。</p>
        ) : (
          <ul className="mt-1.5 flex flex-col gap-1.5 text-ink-soft">
            {Object.entries(stats.by_source).map(([src, bucket]) => (
              <li key={src} className="text-[12.5px]">
                {src}：共 {bucket.total} 个岗位，
                已投递 {bucket.by_stage["已投递"] ?? 0}、面试中 {bucket.by_stage["面试中"] ?? 0}、
                Offer {bucket.by_stage["收到Offer"] ?? 0}
                <span className="ml-1 text-[11px] text-ink-faint">（样本 {bucket.total}，小样本仅作参考）</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">简历版本归因（投递时标记的版本）</p>
        {Object.keys(stats.by_version).length === 0 ? (
          <p className="mt-1 text-[12px] text-ink-faint">
            还没有标记。在岗位详情的「投递所用版本」中选择后，这里会按版本统计进展。
          </p>
        ) : (
          <ul className="mt-1.5 flex flex-col gap-1.5 text-ink-soft">
            {Object.entries(stats.by_version).map(([vname, bucket]) => (
              <li key={vname} className="text-[12.5px]">
                {vname}：已投递 {bucket.by_stage["已投递"] ?? 0}、
                面试中 {bucket.by_stage["面试中"] ?? 0}、
                Offer {bucket.by_stage["收到Offer"] ?? 0}
                <span className="ml-1 text-[11px] text-ink-faint">（样本 {bucket.total}）</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">各阶段岗位数</p>
        <div className="mt-1.5 flex flex-wrap gap-2">
          {Object.entries(stats.by_stage).map(([stage, n]) => (
            <Badge key={stage} variant="secondary" className="text-[11.5px]">{stage} {n}</Badge>
          ))}
          <Badge variant="outline" className="text-[11.5px]">未完成任务 {stats.tasks.open}</Badge>
        </div>
      </div>
      {generation && typeof generation.total === 'number' && <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">AI 生成运行情况</p>
        <p className="mt-1 text-ink-soft">
          共 {generation.total} 次 · 降级 {generation.fallback_count}/{generation.total}
          （{(generation.fallback_rate * 100).toFixed(1)}%）
          {generation.p95_latency_ms !== null ? ` · P95 ${Math.round(generation.p95_latency_ms)}ms` : ''}
        </p>
        <p className="text-[11px] text-ink-faint">只统计来源、延迟和错误类别，不保存 JD、简历或生成正文。</p>
      </div>}
      {funnel && funnel.counts && <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">试用行为统计</p>
        <div className="mt-1 flex flex-wrap gap-2 text-ink-soft">
          <span>保存岗位 {eventCounts.opportunity_saved ?? 0}</span>
          <span>生成材料 {eventCounts.application_kit_generated ?? 0}</span>
          <span>保存素材 {eventCounts.material_saved ?? 0}</span>
          <span>生成分享 {eventCounts.share_created ?? 0}</span>
        </div>
        <p className="text-[11px] text-ink-faint">{funnel.note}</p>
      </div>}
    </div>
  )
}


