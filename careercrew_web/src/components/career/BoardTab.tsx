import { useEffect, useState } from "react"
import { CalendarClock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/workspace/EmptyState"
import { networkErrorText } from "@/lib/errors"
import { BOARD_STAGES, listBoard, listStageChanges, updateBoard, type BoardRow } from "@/lib/career"
import { cn } from "@/lib/utils"
import { isOverdue } from "./dates"

export function BoardTab({ onToast }: { onToast: (m: string) => void }) {
  const [rows, setRows] = useState<BoardRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [logFor, setLogFor] = useState<string | null>(null)
  const [log, setLog] = useState<Array<{ id: string; from_stage: string; to_stage: string; created_at: string }>>([])

  const reload = async () => {
    setLoading(true)
    setError("")
    try {
      setRows(await listBoard())
    } catch (e) {
      setError(networkErrorText(e, "看板加载失败，请稍后重试"))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void reload() }, [])

  const move = async (row: BoardRow, stage: string) => {
    if (row.stage === stage) return
    try {
      const updated = await updateBoard(row.opportunity_id, { stage })
      setRows((prev) => prev.map((r) => (r.opportunity_id === updated.opportunity_id ? updated : r)))
      onToast(`${row.company} → ${stage}`)
    } catch (e) {
      onToast(networkErrorText(e, "更新失败，请稍后重试"))
    }
  }

  const openLog = async (row: BoardRow) => {
    if (logFor === row.opportunity_id) { setLogFor(null); return }
    setLogFor(row.opportunity_id)
    try {
      setLog(await listStageChanges(row.opportunity_id))
    } catch {
      setLog([])
    }
  }

  if (loading) return <p className="text-[12.5px] text-ink-faint">正在加载看板…</p>
  if (error) {
    return (
      <div className="text-[12.5px] text-destructive">
        {error}
        <Button variant="outline" size="sm" className="ml-2 h-[26px] text-[12px]" onClick={() => void reload()}>重试</Button>
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title="看板还是空的"
        description={<>在「岗位准备」收藏岗位后，会自动进入「待准备」列</>}
      />
    )
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 overflow-x-auto md:grid-cols-3 xl:grid-cols-6">
        {BOARD_STAGES.map((stage) => {
          const items = rows.filter((r) => r.stage === stage)
          return (
            <div key={stage} className="min-w-[190px] rounded-[10px] border border-[var(--border-soft)] bg-surface-1 p-2.5">
              <div className="mb-2 flex items-center justify-between text-[12.5px] font-[560] text-ink">
                <span>{stage}</span>
                <Badge variant="secondary" className="text-[10.5px]">{items.length}</Badge>
              </div>
              <div className="flex flex-col gap-2">
                {items.map((row) => (
                  <div key={row.opportunity_id} className="rounded-[8px] border border-[var(--border-soft)] bg-card p-2.5 text-[12px]">
                    <p className="truncate font-[560] text-ink">{row.company} · {row.title}</p>
                    {row.next_action && (
                      <p className="mt-1 flex items-center gap-1 text-ink-soft">
                        <CalendarClock className={cn("h-3 w-3", isOverdue(row.next_action_date) && "text-destructive")} />
                        {row.next_action}
                        {row.next_action_date && <span className="text-ink-faint">（{row.next_action_date}）</span>}
                      </p>
                    )}
                    {row.note && <p className="mt-1 line-clamp-2 text-ink-faint">{row.note}</p>}
                    <div className="mt-2 flex flex-wrap items-center gap-1">
                      {BOARD_STAGES.filter((s) => s !== row.stage).slice(0, 6).map((s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => void move(row, s)}
                          className="rounded border border-[var(--border-soft)] px-1.5 py-0.5 text-[10.5px] text-ink-faint hover:border-ink-faint/60 hover:text-ink"
                        >
                          {s}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() => void openLog(row)}
                        className="rounded px-1 py-0.5 text-[10.5px] text-ink-faint underline-offset-2 hover:text-ink hover:underline"
                      >
                        记录
                      </button>
                    </div>
                    {logFor === row.opportunity_id && (
                      <ul className="mt-2 flex flex-col gap-1 border-t border-[var(--border-soft)] pt-1.5 text-[10.5px] text-ink-faint">
                        {log.length === 0 && <li>暂无变更记录</li>}
                        {log.map((l) => (
                          <li key={l.id}>{l.created_at.slice(0, 10)} · {l.from_stage} → {l.to_stage}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 行动计划 ──
