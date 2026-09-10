import { useEffect, useState } from "react"
import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/workspace/EmptyState"
import { networkErrorText } from "@/lib/errors"
import { createTask, deleteTask, listTasks, patchTask, type ActionItem, type BoardRow } from "@/lib/career"
import { cn } from "@/lib/utils"
import { todayStr, isOverdue, DATE_HINT } from "./dates"
import { RemindersPanel } from "./RemindersPanel"

export function TasksTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
  const [tasks, setTasks] = useState<ActionItem[]>([])
  const [title, setTitle] = useState("")
  const [due, setDue] = useState("")
  const [oppId, setOppId] = useState("")
  const [loading, setLoading] = useState(true)
  const [showDismissed, setShowDismissed] = useState(false)

  const reload = async () => {
    setLoading(true)
    try { setTasks(await listTasks()) } catch { /* 列表失败静默，重试按钮可见 */ }
    finally { setLoading(false) }
  }
  useEffect(() => { void reload() }, [])

  const add = async () => {
    if (!title.trim()) return
    try {
      const created = await createTask({
        title: title.trim(), due_date: due.trim(),
        opportunity_id: oppId || undefined,
      })
      setTasks((prev) => [created, ...prev])
      setTitle("")
      setDue("")
      setOppId("")
      onToast("任务已创建")
    } catch (e) {
      onToast(networkErrorText(e, "创建失败，请稍后重试"))
    }
  }

  const visible = tasks.filter((t) => showDismissed || !t.dismissed)
  const overdue = visible.filter((t) => !t.done && !t.dismissed && isOverdue(t.due_date)).length
  const oppName = (id: string) => {
    const o = opportunities.find((x) => x.opportunity_id === id)
    return o ? `${o.company}·${o.title}` : ""
  }

  return (
    <div className="flex flex-col gap-3">
      <RemindersPanel onToast={onToast} />
      <div className="flex flex-wrap items-center gap-2">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="新任务，例如：准备三道面试题"
               className="h-[32px] w-[260px]" maxLength={300} />
        <Input value={due} onChange={(e) => setDue(e.target.value)} placeholder={DATE_HINT}
               className="h-[32px] w-[130px]" maxLength={10} />
        <select
          value={oppId}
          onChange={(e) => setOppId(e.target.value)}
          aria-label="关联岗位（可选）"
          className="h-[32px] rounded-[7px] border border-[var(--border-soft)] bg-workspace px-2 text-[12.5px] text-ink"
        >
          <option value="">关联岗位（可选）</option>
          {opportunities.map((o) => (
            <option key={o.opportunity_id} value={o.opportunity_id}>{o.company} · {o.title}</option>
          ))}
        </select>
        <Button size="sm" className="h-[30px] text-[12.5px]" onClick={() => void add()} disabled={!title.trim()}>
          <Plus className="h-4 w-4" /> 添加
        </Button>
        <label className="ml-auto flex items-center gap-1 text-[12px] text-ink-faint">
          <input type="checkbox" checked={showDismissed} onChange={(e) => setShowDismissed(e.target.checked)} />
          显示已关闭提醒
        </label>
      </div>
      {overdue > 0 && (
        <p className="rounded-[8px] border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[12px] text-amber-600">
          有 {overdue} 个任务已过期，请处理或延期
        </p>
      )}
      {loading ? (
        <p className="text-[12.5px] text-ink-faint">正在加载任务…</p>
      ) : visible.length === 0 ? (
        <EmptyState title="没有任务" description="把规划拆成可完成的小任务，逐个打勾" />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {visible.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-2 rounded-[8px] border border-[var(--border-soft)] bg-card px-3 py-2 text-[13px]">
              <input
                type="checkbox"
                checked={Boolean(t.done)}
                onChange={async (e) => {
                  try {
                    const updated = await patchTask(t.id, { done: e.target.checked })
                    setTasks((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
                  } catch (err) { onToast(networkErrorText(err, "更新失败")) }
                }}
              />
              <span className={cn("min-w-0 flex-1 truncate", t.done && "text-ink-faint line-through")}>{t.title}</span>
              {t.due_date && (
                <span className={cn("text-[11.5px]", !t.done && isOverdue(t.due_date) ? "text-destructive" : "text-ink-faint")}>
                  截止 {t.due_date}
                </span>
              )}
              {t.opportunity_id && oppName(t.opportunity_id) && (
                <Badge variant="outline" className="text-[10.5px]">{oppName(t.opportunity_id)}</Badge>
              )}
              {t.postponed_count > 0 && <Badge variant="outline" className="text-[10.5px]">已延期 {t.postponed_count}</Badge>}
              <button
                type="button"
                className="text-[11.5px] text-ink-faint hover:text-ink"
                onClick={async () => {
                  try {
                    const updated = await patchTask(t.id, { postponed_due_date: todayStr() })
                    setTasks((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
                    onToast("已延期到今天")
                  } catch (err) { onToast(networkErrorText(err, "延期失败")) }
                }}
              >
                延期
              </button>
              <button
                type="button"
                className="text-[11.5px] text-ink-faint hover:text-ink"
                onClick={async () => {
                  try {
                    const updated = await patchTask(t.id, { dismissed: !t.dismissed })
                    setTasks((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
                  } catch (err) { onToast(networkErrorText(err, "操作失败")) }
                }}
              >
                {t.dismissed ? "恢复提醒" : "关闭提醒"}
              </button>
              <button
                type="button"
                aria-label="删除任务"
                className="text-ink-faint hover:text-destructive"
                onClick={async () => {
                  try { await deleteTask(t.id); setTasks((prev) => prev.filter((x) => x.id !== t.id)) }
                  catch (err) { onToast(networkErrorText(err, "删除失败")) }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── 提醒面板（任务/看板跟进/HR 待办聚合 + ICS 导出） ──

