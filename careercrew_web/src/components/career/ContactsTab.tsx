import { useEffect, useState } from "react"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/workspace/EmptyState"
import { networkErrorText } from "@/lib/errors"
import { createContact, deleteContact, listContacts, updateContact, type BoardRow, type Contact } from "@/lib/career"
import { DATE_HINT } from "./dates"

export function ContactsTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
  const [rows, setRows] = useState<Contact[]>([])
  const [form, setForm] = useState({ contact_name: "", company: "", role: "", channel: "", contact_value: "", notes: "" })
  const [oppId, setOppId] = useState("")
  const [nextDate, setNextDate] = useState("")
  const [error, setError] = useState("")
  const [editingId, setEditingId] = useState<string | null>(null)

  const reload = async () => {
    try { setRows(await listContacts()) } catch (e) { setError(networkErrorText(e)) }
  }
  useEffect(() => { void reload() }, [])

  const reset = () => {
    setForm({ contact_name: "", company: "", role: "", channel: "", contact_value: "", notes: "" })
    setOppId(""); setNextDate(""); setEditingId(null); setError("")
  }

  const startEdit = (r: Contact) => {
    setEditingId(r.id)
    setForm({
      contact_name: r.contact_name, company: r.company, role: r.role,
      channel: r.channel, contact_value: r.contact_value, notes: r.notes,
    })
    setOppId(r.opportunity_id || "")
    setNextDate(r.next_contact_date || "")
    setError("")
  }

  const submit = async () => {
    if (!form.contact_name.trim()) { setError("联系人姓名不能为空"); return }
    try {
      if (editingId) {
        const updated = await updateContact(editingId, {
          ...form, opportunity_id: oppId || undefined, next_contact_date: nextDate || undefined,
        })
        setRows((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
        onToast("联系人已更新")
      } else {
        const created = await createContact({
          ...form, opportunity_id: oppId || undefined, next_contact_date: nextDate || undefined,
        })
        setRows((prev) => [created, ...prev])
        onToast("联系人已保存")
      }
      reset()
    } catch (e) { setError(networkErrorText(e, "保存失败，请稍后重试")) }
  }

  const oppName = (id: string) => {
    const o = opportunities.find((x) => x.opportunity_id === id)
    return o ? `${o.company}·${o.title}` : ""
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="mb-2 text-[12px] text-ink-faint">记录招聘者、面试官、内推人，以及下次联系时间。</p>
        <div className="grid gap-2.5 md:grid-cols-3">
          <Input value={form.contact_name} onChange={(e) => setForm((s) => ({ ...s, contact_name: e.target.value }))}
                 placeholder="姓名 *" maxLength={120} />
          <Input value={form.company} onChange={(e) => setForm((s) => ({ ...s, company: e.target.value }))}
                 placeholder="公司" maxLength={200} />
          <Input value={form.role} onChange={(e) => setForm((s) => ({ ...s, role: e.target.value }))}
                 placeholder="角色（招聘者/面试官/内推人）" maxLength={120} />
          <Input value={form.channel} onChange={(e) => setForm((s) => ({ ...s, channel: e.target.value }))}
                 placeholder="渠道（微信/邮件/Boss）" maxLength={100} />
          <Input value={form.contact_value} onChange={(e) => setForm((s) => ({ ...s, contact_value: e.target.value }))}
                 placeholder="联系方式" maxLength={300} />
          <Input value={nextDate} onChange={(e) => setNextDate(e.target.value)}
                 placeholder={DATE_HINT} maxLength={10} />
        </div>
        <div className="mt-2.5 grid gap-2.5 md:grid-cols-2">
          <Input value={form.notes} onChange={(e) => setForm((s) => ({ ...s, notes: e.target.value }))}
                 placeholder="备注（怎么认识的、聊了什么）" maxLength={2000} />
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
        <div className="mt-2.5 flex gap-2">
          <Button size="sm" className="h-[28px] text-[12.5px]" onClick={() => void submit()}>
            {editingId ? "保存修改" : "保存联系人"}
          </Button>
          {editingId && (
            <Button size="sm" variant="ghost" className="h-[28px] text-[12.5px]" onClick={reset}>取消</Button>
          )}
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="还没有联系人" description="把 HR、面试官、内推人记下来，跟进不再靠记忆" />
      ) : (
        <ul className="grid gap-2.5 md:grid-cols-2">
          {rows.map((r) => (
            <li key={r.id} className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-[560] text-ink">
                  {r.contact_name}
                  {r.company ? ` · ${r.company}` : ""}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-[11.5px]">
                  <button type="button" className="text-ink-faint hover:text-ink" onClick={() => startEdit(r)}>
                    编辑
                  </button>
                  <button type="button" aria-label="删除联系人" className="text-ink-faint hover:text-destructive"
                          onClick={async () => {
                            try { await deleteContact(r.id); setRows((p) => p.filter((x) => x.id !== r.id)) }
                            catch (e) { onToast(networkErrorText(e, "删除失败")) } }}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </span>
              </div>
              <p className="mt-1 flex flex-wrap gap-x-2 text-ink-soft">
                {r.role && <span>{r.role}</span>}
                {r.channel && <span>{r.channel}</span>}
                {r.contact_value && <span>{r.contact_value}</span>}
              </p>
              {r.next_contact_date && <p className="mt-0.5 text-amber-600">下次联系：{r.next_contact_date}</p>}
              {r.opportunity_id && oppName(r.opportunity_id) && (
                <Badge variant="outline" className="mt-1 text-[10.5px]">{oppName(r.opportunity_id)}</Badge>
              )}
              {r.notes && <p className="mt-1 line-clamp-2 text-ink-faint">{r.notes}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── 效果统计 ──
