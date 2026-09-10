import { useEffect, useState } from "react"
import { Download } from "lucide-react"
import { BellRing } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { networkErrorText } from "@/lib/errors"
import { listReminders, type ReminderItem } from "@/lib/career"
import { downloadRemindersIcs } from "@/lib/career"

export function RemindersPanel({ onToast }: { onToast: (m: string) => void }) {
  const [items, setItems] = useState<ReminderItem[] | null>(null)

  useEffect(() => {
    listReminders().then((d) => setItems(d.items || [])).catch(() => setItems([]))
  }, [])

  const downloadIcs = async () => {
    try {
      const blob = await downloadRemindersIcs()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "careercrew.ics"
      a.click()
      URL.revokeObjectURL(url)
      onToast("日历文件已导出，可导入到系统日历")
    } catch (e) { onToast(networkErrorText(e, "导出失败，请稍后重试")) }
  }

  const kindLabel: Record<string, string> = {
    task_overdue: "逾期", task_due: "将到期",
    action_overdue: "跟进逾期", action_due: "待跟进", followup: "HR 待办",
  }

  return (
    <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3" data-testid="reminders">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-[13px] font-[560] text-ink">
          <BellRing className="h-4 w-4" /> 提醒
        </h3>
        <Button variant="outline" size="sm" className="h-[26px] text-[12px]" onClick={() => void downloadIcs()}>
          <Download className="h-3.5 w-3.5" /> 导出 ICS 日历
        </Button>
      </div>
      {!items ? (
        <p className="mt-1.5 text-[12px] text-ink-faint">正在加载提醒…</p>
      ) : items.length === 0 ? (
        <p className="mt-1.5 text-[12px] text-ink-faint">最近 7 天没有到期任务或跟进。</p>
      ) : (
        <ul className="mt-1.5 flex flex-col gap-1">
          {items.slice(0, 8).map((r, i) => (
            <li key={`${r.kind}-${r.ref_id}-${i}`} className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <Badge variant={r.kind.includes("overdue") ? "destructive" : "secondary"} className="text-[10.5px]">
                {kindLabel[r.kind] ?? r.kind}
              </Badge>
              <span className="min-w-0 flex-1 truncate text-ink-soft">{r.title}</span>
              {r.date && <span className="text-[11px] text-ink-faint">{r.date}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
