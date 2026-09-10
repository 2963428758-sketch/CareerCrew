import { useCallback, useEffect, useState } from "react"
import {
  Briefcase, CalendarClock, ClipboardList, FileText, Handshake, Loader2,
  MessagesSquare, Mic, Sparkles,
} from "lucide-react"

import { networkErrorText } from "@/lib/errors"
import { getOpportunityTimeline, type TimelineEvent } from "@/lib/career"

const KIND_META: Record<TimelineEvent["kind"], { label: string; icon: typeof Briefcase; color: string }> = {
  created: { label: "收藏", icon: Briefcase, color: "text-ink" },
  resume_version: { label: "简历", icon: FileText, color: "text-amber-600" },
  session: { label: "会话", icon: Mic, color: "text-rose-600" },
  stage: { label: "阶段", icon: Sparkles, color: "text-emerald-600" },
  task: { label: "行动", icon: ClipboardList, color: "text-blue-600" },
  followup: { label: "HR", icon: MessagesSquare, color: "text-violet-600" },
  offer: { label: "Offer", icon: Handshake, color: "text-emerald-600" },
  review: { label: "复盘", icon: CalendarClock, color: "text-amber-600" },
}

/** 岗位档案时间线：一个岗位从收藏到 Offer 的完整过程，倒序一页可见。 */
export function OpportunityTimeline({ opportunityId }: { opportunityId: string }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const data = await getOpportunityTimeline(opportunityId)
      setEvents(data.events || [])
    } catch (e) {
      setError(networkErrorText(e, "时间线加载失败，请稍后重试"))
    } finally {
      setLoading(false)
    }
  }, [opportunityId])

  useEffect(() => { void reload() }, [reload])

  return (
    <div className="flex flex-col gap-2" data-testid="opportunity-timeline">
      <h3 className="text-[13.5px] font-[560] text-ink">岗位时间线</h3>
      {loading ? (
        <p className="flex items-center gap-1.5 text-[12px] text-ink-faint">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在加载…
        </p>
      ) : error ? (
        <p className="text-[12px] text-destructive">{error}</p>
      ) : !events || events.length === 0 ? (
        <p className="text-[12px] text-ink-faint">还没有动态。</p>
      ) : (
        <ol className="flex flex-col">
          {events.map((e, i) => {
            const meta = KIND_META[e.kind] ?? KIND_META.created
            const Icon = meta.icon
            return (
              <li key={`${e.kind}-${e.at}-${i}`} className="flex gap-2.5">
                <div className="flex flex-col items-center">
                  <Icon className={"mt-1 h-3.5 w-3.5 shrink-0 " + meta.color} strokeWidth={1.8} />
                  {i < events.length - 1 && <span className="my-1 w-px flex-1 bg-[var(--border-soft)]" />}
                </div>
                <div className="min-w-0 flex-1 pb-3">
                  <p className="text-[12.5px] font-[520] text-ink">{e.title}</p>
                  {e.detail && <p className="mt-0.5 line-clamp-2 break-words text-[11.5px] text-ink-faint">{e.detail}</p>}
                  {e.at && (
                    <p className="mt-0.5 text-[10.5px] text-ink-faint">
                      {new Date(e.at).toLocaleString()}
                    </p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
