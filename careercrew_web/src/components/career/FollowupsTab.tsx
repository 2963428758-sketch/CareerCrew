import { useEffect, useState } from "react"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { networkErrorText } from "@/lib/errors"
import { createFollowup, deleteFollowup, listFollowups, resolveFollowup, setReplyDraft, type BoardRow, type HRFollowup } from "@/lib/career"
import { cn } from "@/lib/utils"

export function FollowupsTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
  const [rows, setRows] = useState<HRFollowup[]>([])
  const [form, setForm] = useState({ company: "", title: "", channel: "", content: "", todo_note: "" })
  const [oppId, setOppId] = useState("")
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [error, setError] = useState("")

  const reload = async () => {
    try { setRows(await listFollowups()) } catch (e) { setError(networkErrorText(e)) }
  }
  useEffect(() => { void reload() }, [])

  const submit = async () => {
    if (!form.company.trim() || !form.content.trim()) { setError("公司与沟通内容不能为空"); return }
    try {
      const created = await createFollowup({
        company: form.company.trim(), title: form.title, channel: form.channel,
        content: form.content, todo_note: form.todo_note,
        opportunity_id: oppId || undefined,
      })
      setRows((prev) => [created, ...prev])
      setForm({ company: "", title: "", channel: "", content: "", todo_note: "" })
      setOppId("")
      setError("")
      onToast("HR 沟通已记录")
    } catch (e) { setError(networkErrorText(e, "保存失败，请稍后重试")) }
  }

  const oppName = (id: string) => {
    const o = opportunities.find((x) => x.opportunity_id === id)
    return o ? `${o.company}·${o.title}` : ""
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="mb-2 text-[12px] text-ink-faint">手动录入 HR 沟通内容；回复草稿仅作准备，不会被自动发送。</p>
        <div className="grid gap-2.5 md:grid-cols-3">
          <Input value={form.company} onChange={(e) => setForm((s) => ({ ...s, company: e.target.value }))} placeholder="公司 *" />
          <Input value={form.title} onChange={(e) => setForm((s) => ({ ...s, title: e.target.value }))} placeholder="岗位" />
          <Input value={form.channel} onChange={(e) => setForm((s) => ({ ...s, channel: e.target.value }))} placeholder="渠道（Boss/邮件…）" />
        </div>
        <Textarea value={form.content} onChange={(e) => setForm((s) => ({ ...s, content: e.target.value }))}
                  placeholder="HR 原话 / 沟通内容 *" className="mt-2.5 min-h-[64px]" />
        <div className="mt-2.5 grid gap-2.5 md:grid-cols-2">
          <Input value={form.todo_note} onChange={(e) => setForm((s) => ({ ...s, todo_note: e.target.value }))}
                 placeholder="待办（例如：周三前回复时间）" className="h-[32px]" />
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
        </div>
        {error && <p className="mt-1.5 text-[12px] text-destructive">{error}</p>}
        <Button size="sm" className="mt-2.5 h-[28px] text-[12.5px]" onClick={() => void submit()}>保存记录</Button>
      </div>
      {rows.map((r) => (
        <div key={r.id} className={cn("rounded-[10px] border p-3 text-[12.5px]",
          r.resolved ? "border-[var(--border-soft)] bg-surface-1 text-ink-faint" : "border-[var(--border-soft)] bg-card")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-[560] text-ink">{r.company}{r.title ? ` · ${r.title}` : ""}</span>
            <span className="flex items-center gap-2 text-[11.5px]">
              {r.channel && <Badge variant="outline" className="text-[10.5px]">{r.channel}</Badge>}
              {r.resolved ? "已处理" : "待处理"}
              {r.opportunity_id && oppName(r.opportunity_id) && (
                <Badge variant="outline" className="text-[10.5px]">{oppName(r.opportunity_id)}</Badge>
              )}
              <button type="button" className="hover:text-ink" onClick={async () => {
                try { const updated = await resolveFollowup(r.id); setRows((p) => p.map((x) => (x.id === updated.id ? updated : x))) }
                catch (e) { onToast(networkErrorText(e)) } }}>
                {r.resolved ? "重新打开" : "标记处理完成"}
              </button>
              <button type="button" aria-label="删除记录" className="hover:text-destructive" onClick={async () => {
                try { await deleteFollowup(r.id); setRows((p) => p.filter((x) => x.id !== r.id)) }
                catch (e) { onToast(networkErrorText(e)) } }}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
          <p className="mt-1.5 whitespace-pre-wrap break-words text-ink-soft">{r.content}</p>
          {r.todo_note && <p className="mt-1 text-amber-600">待办：{r.todo_note}</p>}
          <div className="mt-2 flex flex-col gap-1.5 border-t border-[var(--border-soft)] pt-2">
            <Textarea
              value={drafts[r.id] ?? r.reply_draft}
              onChange={(e) => setDrafts((s) => ({ ...s, [r.id]: e.target.value }))}
              placeholder="回复草稿（不会自动发送）"
              className="min-h-[56px]" />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" className="h-[26px] text-[12px]" onClick={async () => {
                try {
                  const confirmed = false
                  const updated = await setReplyDraft(r.id, { reply_draft: drafts[r.id] ?? r.reply_draft, confirmed })
                  setRows((p) => p.map((x) => (x.id === updated.id ? updated : x)))
                  onToast("草稿已保存（未确认）")
                } catch (e) { onToast(networkErrorText(e)) }
              }}>存草稿</Button>
              <Button size="sm" className="h-[26px] text-[12px]" onClick={async () => {
                try {
                  const updated = await setReplyDraft(r.id, { reply_draft: drafts[r.id] ?? r.reply_draft, confirmed: true })
                  setRows((p) => p.map((x) => (x.id === updated.id ? updated : x)))
                  onToast("已确认草稿，请自行到对应渠道发送")
                } catch (e) { onToast(networkErrorText(e)) }
              }}>确认草稿</Button>
              {r.draft_confirmed && <span className="text-[11px] text-emerald-600">已确认（发送由你完成）</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

