import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  CalendarClock, ClipboardList, Compass, Download, FileSpreadsheet, ListTodo,
  MessagesSquare, Mic, Plus, RefreshCw, Search, Trash2, TrendingUp,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { EmptyState } from "@/components/workspace/EmptyState"
import { ToastBubble } from "@/components/conversation/ToastBubble"
import { useToast } from "@/hooks/useToast"
import { networkErrorText } from "@/lib/errors"
import {
  BOARD_STAGES, createFollowup, createMaterial, createOffer, createRealInterview,
  createTask, deleteFollowup, deleteMaterial, deleteOffer, deleteRealInterview, deleteTask,
  getStats, globalSearch, listBoard, listFollowups, listInterviewReports, listMaterials,
  listOffers, listRealInterviews, listStageChanges, listTasks, patchTask, resolveFollowup,
  setReplyDraft, updateBoard, updateMaterial, type ActionItem, type BoardRow,
  type HRFollowup, type InterviewReport, type JobStats,
  type Material, type Offer, type RealInterviewRecord, type SearchResult,
} from "@/lib/career"
import { cn } from "@/lib/utils"

const TABS = [
  { id: "board", label: "进度看板", icon: Compass },
  { id: "tasks", label: "行动计划", icon: ListTodo },
  { id: "materials", label: "素材库", icon: ClipboardList },
  { id: "followups", label: "HR 跟进", icon: MessagesSquare },
  { id: "offers", label: "Offer 对比", icon: FileSpreadsheet },
  { id: "reviews", label: "面试复盘", icon: Mic },
  { id: "stats", label: "效果统计", icon: TrendingUp },
  { id: "privacy", label: "数据与隐私", icon: Download },
] as const

type TabId = (typeof TABS)[number]["id"]

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function isOverdue(due: string): boolean {
  return Boolean(due) && due < todayStr()
}

/** 日期输入的通用格式提示。 */
const DATE_HINT = "格式 YYYY-MM-DD"

// ── 看板 ──

function BoardTab({ onToast }: { onToast: (m: string) => void }) {
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

function TasksTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
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

// ── 素材库 ──

const EMPTY_MATERIAL = { name: "", background: "", role: "", actions: "", results: "", tags: "" }

function MaterialsTab({ onToast }: { onToast: (m: string) => void }) {
  const [materials, setMaterials] = useState<Material[]>([])
  const [form, setForm] = useState(EMPTY_MATERIAL)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState("")

  const reload = async () => {
    try { setMaterials(await listMaterials()) } catch (e) { setError(networkErrorText(e)) }
  }
  useEffect(() => { void reload() }, [])

  const reset = () => { setForm(EMPTY_MATERIAL); setEditingId(null); setOpen(false); setError("") }

  const submit = async () => {
    if (!form.name.trim()) { setError("素材名称不能为空"); return }
    const payload = {
      name: form.name.trim(), background: form.background, role: form.role,
      actions: form.actions, results: form.results, confirmed: true,
      tags: form.tags.split(/[,，]/).map((t) => t.trim()).filter(Boolean).slice(0, 10),
    }
    try {
      if (editingId) {
        const updated = await updateMaterial(editingId, payload)
        setMaterials((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
        onToast("素材已更新")
      } else {
        const created = await createMaterial(payload)
        setMaterials((prev) => [created, ...prev])
        onToast("素材已保存")
      }
      reset()
    } catch (e) {
      setError(networkErrorText(e, "保存失败，请稍后重试"))
    }
  }

  const fields: Array<{ key: keyof typeof EMPTY_MATERIAL; label: string; long?: boolean }> = [
    { key: "name", label: "项目名称 *" },
    { key: "background", label: "项目背景（STAR：背景）", long: true },
    { key: "role", label: "我的职责", long: true },
    { key: "actions", label: "关键行动", long: true },
    { key: "results", label: "成果与量化数据", long: true },
    { key: "tags", label: "标签（逗号分隔）" },
  ]

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-ink-faint">同一份经过确认的素材，供简历与面试共同引用，避免不同顾问说法不一致。</p>
        <Button size="sm" variant="outline" className="h-[28px] text-[12px]" onClick={() => { setOpen((v) => !v); if (!open) { reset(); setOpen(true) } }}>
          <Plus className="h-4 w-4" /> 新建素材
        </Button>
      </div>
      {open && (
        <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
          <div className="grid gap-2.5 md:grid-cols-2">
            {fields.map((f) => (
              <label key={f.key} className={cn("flex flex-col gap-1 text-[12.5px] text-ink-soft", f.long && "md:col-span-2")}>
                {f.label}
                {f.long ? (
                  <Textarea value={form[f.key]} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
                            className="min-h-[64px]" />
                ) : (
                  <Input value={form[f.key]} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))} />
                )}
              </label>
            ))}
          </div>
          {error && <p className="mt-2 text-[12px] text-destructive">{error}</p>}
          <div className="mt-2.5 flex gap-2">
            <Button size="sm" className="h-[28px] text-[12.5px]" onClick={() => void submit()}>保存素材</Button>
            <Button size="sm" variant="ghost" className="h-[28px] text-[12.5px]" onClick={reset}>取消</Button>
          </div>
        </div>
      )}
      {materials.length === 0 ? (
        <EmptyState title="还没有项目素材" description="记录真实项目：背景、职责、行动、成果" />
      ) : (
        <ul className="grid gap-2.5 md:grid-cols-2">
          {materials.map((m) => (
            <li key={m.id} className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate font-[560] text-ink">{m.name}</span>
                <span className="flex shrink-0 items-center gap-1">
                  <button type="button" className="text-[11.5px] text-ink-faint hover:text-ink"
                          onClick={() => { setEditingId(m.id); setOpen(true); setForm({
                            name: m.name, background: m.background, role: m.role, actions: m.actions,
                            results: m.results, tags: (m.tags || []).join(","), }) }}>
                    编辑
                  </button>
                  <button type="button" aria-label="删除素材" className="text-ink-faint hover:text-destructive"
                          onClick={async () => {
                            try { await deleteMaterial(m.id); setMaterials((prev) => prev.filter((x) => x.id !== m.id)) }
                            catch (e) { onToast(networkErrorText(e, "删除失败")) } }}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {(m.tags || []).map((t) => <Badge key={t} variant="secondary" className="text-[10.5px]">{t}</Badge>)}
                {m.confirmed && <Badge variant="outline" className="text-[10.5px]">已确认</Badge>}
              </div>
              {m.results && <p className="mt-1.5 line-clamp-2 text-ink-soft">成果：{m.results}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── HR 跟进 ──

function FollowupsTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
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

// ── Offer 对比 ──

const OFFER_WEIGHTS = [
  { key: "base_salary", label: "薪资" },
  { key: "location", label: "地点" },
  { key: "work_mode", label: "工作方式" },
  { key: "growth", label: "成长" },
] as const

function OffersTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
  const [offers, setOffers] = useState<Offer[]>([])
  const [weights, setWeights] = useState<Record<string, number>>({
    base_salary: 4, location: 3, work_mode: 2, growth: 3 })
  const [form, setForm] = useState({ company: "", title: "", base_salary: "", bonus: "", equity: "", location: "", work_mode: "", growth: "", notes: "" })
  const [oppId, setOppId] = useState("")
  const [error, setError] = useState("")

  const reload = async () => {
    try { setOffers(await listOffers()) } catch (e) { setError(networkErrorText(e)) }
  }
  useEffect(() => { void reload() }, [])

  const submit = async () => {
    if (!form.company.trim()) { setError("公司名称不能为空"); return }
    try {
      const created = await createOffer({ ...form, opportunity_id: oppId || undefined })
      setOffers((prev) => [created, ...prev])
      setForm({ company: "", title: "", base_salary: "", bonus: "", equity: "", location: "", work_mode: "", growth: "", notes: "" })
      setOppId("")
      setError("")
      onToast("Offer 已记录")
    } catch (e) { setError(networkErrorText(e, "保存失败，请稍后重试")) }
  }

  /** 满意度粗评：把非空维度计分（填写=1，空=0），乘以权重；空值显式提示。 */
  const scoreOf = (offer: Offer) => {
    let score = 0, max = 0
    for (const dim of OFFER_WEIGHTS) {
      const weight = weights[dim.key] ?? 0
      max += weight * 10
      const value = String((offer as unknown as Record<string, unknown>)[dim.key] ?? "")
      score += weight * (value.trim() ? 10 : 0)
    }
    return { score, max, incomplete: OFFER_WEIGHTS.some((d) => !String((offer as unknown as Record<string, unknown>)[d.key] ?? "").trim()) }
  }
  const best = offers.length > 1 ? Math.max(...offers.map((o) => scoreOf(o).score)) : -1

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2 rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        {OFFER_WEIGHTS.map((d) => (
          <label key={d.key} className="flex flex-col gap-1 text-[11.5px] text-ink-faint">
            {d.label}权重 {weights[d.key]}
            <input type="range" min={0} max={5} value={weights[d.key]}
                   onChange={(e) => setWeights((s) => ({ ...s, [d.key]: Number(e.target.value) }))}
                   className="w-[110px]" />
          </label>
        ))}
      </div>
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <div className="grid gap-2.5 md:grid-cols-4">
          <Input value={form.company} onChange={(e) => setForm((s) => ({ ...s, company: e.target.value }))} placeholder="公司 *" />
          <Input value={form.title} onChange={(e) => setForm((s) => ({ ...s, title: e.target.value }))} placeholder="岗位" />
          <Input value={form.base_salary} onChange={(e) => setForm((s) => ({ ...s, base_salary: e.target.value }))} placeholder="月薪/年薪" />
          <Input value={form.bonus} onChange={(e) => setForm((s) => ({ ...s, bonus: e.target.value }))} placeholder="奖金" />
          <Input value={form.equity} onChange={(e) => setForm((s) => ({ ...s, equity: e.target.value }))} placeholder="股权/期权" />
          <Input value={form.location} onChange={(e) => setForm((s) => ({ ...s, location: e.target.value }))} placeholder="工作地点" />
          <Input value={form.work_mode} onChange={(e) => setForm((s) => ({ ...s, work_mode: e.target.value }))} placeholder="工作方式（ onsite/remote）" />
          <Input value={form.growth} onChange={(e) => setForm((s) => ({ ...s, growth: e.target.value }))} placeholder="成长方向" />
        </div>
        <Textarea value={form.notes} onChange={(e) => setForm((s) => ({ ...s, notes: e.target.value }))} placeholder="其他备注" className="mt-2.5 min-h-[48px]" />
        <select
          value={oppId}
          onChange={(e) => setOppId(e.target.value)}
          aria-label="关联岗位（可选）"
          className="mt-2.5 h-[32px] rounded-[7px] border border-[var(--border-soft)] bg-workspace px-2 text-[12.5px] text-ink"
        >
          <option value="">关联岗位（可选）</option>
          {opportunities.map((o) => (
            <option key={o.opportunity_id} value={o.opportunity_id}>{o.company} · {o.title}</option>
          ))}
        </select>
        {error && <p className="mt-1.5 text-[12px] text-destructive">{error}</p>}
        <Button size="sm" className="mt-2.5 h-[28px] text-[12.5px]" onClick={() => void submit()}>添加 Offer</Button>
      </div>
      {offers.length === 0 ? (
        <EmptyState title="还没有录入 Offer" description="把薪酬构成、地点、工作方式填进来对比" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-[var(--border-soft)] text-left text-ink-faint">
                <th className="p-2">公司 / 岗位</th>
                <th className="p-2">薪资构成</th>
                <th className="p-2">地点 / 方式</th>
                <th className="p-2">成长</th>
                <th className="p-2">加权参考</th>
                <th className="p-2" />
              </tr>
            </thead>
            <tbody>
              {offers.map((o) => {
                const s = scoreOf(o)
                return (
                  <tr key={o.id} className="border-b border-[var(--border-soft)] align-top">
                    <td className="p-2 font-[560] text-ink">{o.company}{o.title ? ` · ${o.title}` : ""}</td>
                    <td className="p-2 text-ink-soft">
                      {[["月薪", o.base_salary], ["奖金", o.bonus], ["股权", o.equity]].map(([k, v]) => (
                        <p key={k as string}>
                          {k}：{String(v).trim() || <span className="text-destructive">待确认</span>}
                        </p>
                      ))}
                    </td>
                    <td className="p-2 text-ink-soft">
                      <p>地点：{o.location.trim() || <span className="text-destructive">待确认</span>}</p>
                      <p>方式：{o.work_mode.trim() || <span className="text-destructive">待确认</span>}</p>
                    </td>
                    <td className="p-2 text-ink-soft">{o.growth.trim() || <span className="text-destructive">待确认</span>}</td>
                    <td className="p-2">
                      <span className={cn("font-[560]", s.score === best && "text-emerald-600")}>
                        {s.score}/{s.max}
                      </span>
                      {s.incomplete && <p className="text-[10.5px] text-ink-faint">有空项，仅供参考</p>}
                    </td>
                    <td className="p-2">
                      <button type="button" aria-label="删除Offer" className="text-ink-faint hover:text-destructive"
                              onClick={async () => {
                                try { await deleteOffer(o.id); setOffers((p) => p.filter((x) => x.id !== o.id)) }
                                catch (e) { onToast(networkErrorText(e)) } }}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── 面试复盘（真实录入 + 模拟报告） ──

function ReviewsTab({ onToast }: { onToast: (m: string) => void }) {
  const navigate = useNavigate()
  const [records, setRecords] = useState<RealInterviewRecord[]>([])
  const [reports, setReports] = useState<InterviewReport[]>([])
  const [company, setCompany] = useState("")
  const [date, setDate] = useState("")
  const [questionText, setQuestionText] = useState("")
  const [reflection, setReflection] = useState("")
  const [error, setError] = useState("")

  const reload = async () => {
    try {
      setRecords(await listRealInterviews())
      setReports(await listInterviewReports())
    } catch (e) { setError(networkErrorText(e)) }
  }
  useEffect(() => { void reload() }, [])

  const startPractice = (report: InterviewReport) => {
    const weaknesses = (report.report.weaknesses || [])
      .map((w) => (typeof w === "string" ? w : String((w as Record<string, unknown>).question ?? "")))
      .filter(Boolean)
    const summary = typeof report.report.summary === "string" && report.report.summary
      ? report.report.summary
      : weaknesses.join("；")
    sessionStorage.setItem("interview:practice", (summary || "综合训练").slice(0, 300))
    navigate("/interview")
  }

  const submit = async () => {
    if (!company.trim() || !questionText.trim()) { setError("公司与面试题不能为空"); return }
    try {
      const created = await createRealInterview({
        company: company.trim(), interview_date: date.trim(),
        questions: questionText.split("\n").filter((l) => l.trim()).map((q) => ({
          question: q.trim(), answer: "", reflection: reflection.trim() })),
        overall_reflection: reflection.trim(),
      })
      setRecords((prev) => [created, ...prev])
      setCompany(""); setDate(""); setQuestionText(""); setReflection("")
      setError("")
      onToast("真实面试复盘已保存")
    } catch (e) { setError(networkErrorText(e, "保存失败，请稍后重试")) }
  }

  return (
    <div className="flex flex-col gap-3">
      {reports.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-[13.5px] font-[560] text-ink">模拟面试复盘报告</h3>
          {reports.map((r) => {
            const weak = (r.report.weaknesses || []).map((w) =>
              typeof w === "string" ? w : String((w as Record<string, unknown>).question ?? "")).filter(Boolean)
            return (
              <div key={r.id} className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-[560] text-ink">
                    {r.created_at.slice(0, 10)} · {r.report.scored_questions}/{r.report.total_questions} 题已评分
                    {r.report.avg_score !== null && ` · 均分 ${r.report.avg_score}`}
                    <span className="ml-1.5 text-[10.5px] text-ink-faint">
                      {r.report.source === "llm" ? "AI 汇总" : "规则汇总"}
                    </span>
                  </span>
                  <Button size="sm" variant="outline" className="h-[26px] text-[12px]" onClick={() => startPractice(r)}>
                    一键复练薄弱项
                  </Button>
                </div>
                {r.report.summary && <p className="mt-1.5 text-ink-soft">{r.report.summary}</p>}
                {weak.length > 0 && <p className="mt-1 text-amber-600">薄弱点：{weak.join("；")}</p>}
              </div>
            )
          })}
        </div>
      )}
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="mb-2 text-[12px] text-ink-faint">记录真实面试的问题与自我反思；薄弱点会转成练习素材（区别于模拟面试结果）。模拟面试的整场报告在面试页点击「生成整场复盘报告」后出现在这里。</p>
        <div className="grid gap-2.5 md:grid-cols-2">
          <Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="公司 *" />
          <Input value={date} onChange={(e) => setDate(e.target.value)} placeholder={DATE_HINT} maxLength={10} />
        </div>
        <Textarea value={questionText} onChange={(e) => setQuestionText(e.target.value)}
                  placeholder="每行一道面试题 *" className="mt-2.5 min-h-[64px]" />
        <Textarea value={reflection} onChange={(e) => setReflection(e.target.value)}
                  placeholder="自我反思 / 薄弱点" className="mt-2.5 min-h-[48px]" />
        {error && <p className="mt-1.5 text-[12px] text-destructive">{error}</p>}
        <Button size="sm" className="mt-2.5 h-[28px] text-[12.5px]" onClick={() => void submit()}>保存复盘</Button>
      </div>
      {records.map((r) => (
        <div key={r.id} className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
          <div className="flex items-center justify-between">
            <span className="font-[560] text-ink">{r.company}{r.interview_date ? ` · ${r.interview_date}` : ""}</span>
            <button type="button" aria-label="删除复盘" className="text-ink-faint hover:text-destructive"
                    onClick={async () => {
                      try { await deleteRealInterview(r.id); setRecords((p) => p.filter((x) => x.id !== r.id)) }
                      catch (e) { onToast(networkErrorText(e)) } }}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
          <ul className="mt-1.5 list-inside list-disc text-ink-soft">
            {(r.questions || []).slice(0, 8).map((q, i) => <li key={i} className="truncate">{q.question}</li>)}
          </ul>
          {(r.weak_points || []).length > 0 && (
            <p className="mt-1.5 text-amber-600">薄弱点：{(r.weak_points || []).join("；")}</p>
          )}
        </div>
      ))}
    </div>
  )
}

// ── 效果统计 ──

function StatsTab() {
  const [stats, setStats] = useState<JobStats | null>(null)
  const [error, setError] = useState("")
  useEffect(() => { getStats().then(setStats).catch((e) => setError(networkErrorText(e))) }, [])

  if (error) return <p className="text-[12.5px] text-destructive">{error}</p>
  if (!stats) return <p className="text-[12.5px] text-ink-faint">正在统计…</p>

  const rateText = (r: { numerator: number; denominator: number; rate: number | null }) =>
    `${r.numerator}/${r.denominator}` + (r.rate !== null ? `（${(r.rate * 100).toFixed(1)}%）` : "（样本不足）")

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
        <p className="font-[560] text-ink">各阶段岗位数</p>
        <div className="mt-1.5 flex flex-wrap gap-2">
          {Object.entries(stats.by_stage).map(([stage, n]) => (
            <Badge key={stage} variant="secondary" className="text-[11.5px]">{stage} {n}</Badge>
          ))}
          <Badge variant="outline" className="text-[11.5px]">未完成任务 {stats.tasks.open}</Badge>
        </div>
      </div>
    </div>
  )
}

// ── 数据与隐私 ──

function PrivacyTab({ onToast }: { onToast: (m: string) => void }) {
  const [keyword, setKeyword] = useState("")
  const [result, setResult] = useState<SearchResult | null>(null)
  const [confirmPurge, setConfirmPurge] = useState(false)

  const doExport = async () => {
    try {
      const { exportPrivacyData } = await import("@/lib/career")
      const data = await exportPrivacyData()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `careercrew-数据导出-${todayStr()}.json`
      a.click()
      URL.revokeObjectURL(url)
      onToast("个人资料已导出")
    } catch (e) { onToast(networkErrorText(e, "导出失败，请稍后重试")) }
  }

  return (
    <div className="flex flex-col gap-3 text-[13px]">
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">全局搜索（公司 / 岗位 / 素材 / 任务）</p>
        <div className="mt-2 flex items-center gap-2">
          <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索关键词"
                 className="h-[32px] w-[260px]" />
          <Button size="sm" variant="outline" className="h-[30px] text-[12.5px]" disabled={!keyword.trim()}
                  onClick={async () => {
                    try { setResult(await globalSearch(keyword.trim())) } catch (e) { onToast(networkErrorText(e)) } }}>
            <Search className="h-4 w-4" /> 搜索
          </Button>
        </div>
        {result && (
          <div className="mt-2 flex flex-col gap-1.5 text-[12px] text-ink-soft">
            <p>岗位 {result.opportunities.length} 条 · 素材 {result.materials.length} 条 · 真实面试 {result.real_interviews.length} 条 · Offer {result.offers.length} 条 · 任务 {result.tasks.length} 条</p>
            {result.opportunities.map((o) => (
              <Link key={o.id} to={`/preparation?opportunity=${o.id}`} className="hover:text-ink">
                岗位：{o.company} · {o.title}
              </Link>
            ))}
            {result.materials.map((m) => <p key={m.id}>素材：{m.name}</p>)}
            {result.tasks.map((t) => <p key={t.id}>任务：{t.title}</p>)}
          </div>
        )}
      </div>
      <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3">
        <p className="font-[560] text-ink">导出我的全部数据</p>
        <p className="mt-1 text-[12px] text-ink-faint">包含岗位、版本、素材、任务、HR 记录、Offer 与真实面试复盘（JSON）。</p>
        <Button size="sm" variant="outline" className="mt-2 h-[28px] text-[12.5px]" onClick={() => void doExport()}>
          <Download className="h-4 w-4" /> 导出 JSON
        </Button>
      </div>
      <div className="rounded-[10px] border border-destructive/40 bg-card p-3">
        <p className="font-[560] text-destructive">删除全部求职数据</p>
        <p className="mt-1 text-[12px] text-ink-faint">
          删除岗位准备（含简历版本与准备会话）与求职跟进数据；不影响对话历史与简历库。
        </p>
        <Button size="sm" variant="destructive" className="mt-2 h-[28px] text-[12.5px]" onClick={() => setConfirmPurge(true)}>
          删除我的全部求职数据
        </Button>
      </div>
      <ConfirmDialog
        open={confirmPurge}
        title="确认删除全部求职数据？"
        message="岗位、简历版本、准备会话、素材、任务、HR 记录、Offer 与复盘都会被删除，不可恢复。"
        confirmLabel="全部删除"
        onConfirm={async () => {
          try {
            const { purgePrivacyData } = await import("@/lib/career")
            const result = await purgePrivacyData()
            onToast(`已删除 ${Object.values(result.deleted || {}).reduce((a, b) => a + b, 0)} 条记录`)
          } catch (e) { onToast(networkErrorText(e, "删除失败，请稍后重试")) }
          setConfirmPurge(false)
        }}
        onClose={() => setConfirmPurge(false)}
      />
    </div>
  )
}

// ── 页面 ──

export default function CareerCenterPage() {
  const [tab, setTab] = useState<TabId>("board")
  const { toast, showToast } = useToast()
  // 页面级加载一次岗位列表：任务/HR/Offer 创建时可关联岗位，形成完整岗位档案
  const [opportunities, setOpportunities] = useState<BoardRow[]>([])
  useEffect(() => { listBoard().then(setOpportunities).catch(() => undefined) }, [])

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-[var(--border-soft)] px-4 py-3 md:px-6">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-button-ink text-on-ink">
            <Compass className="h-4 w-4" />
          </span>
          <div>
            <h1 className="text-[15px] font-[600] text-ink">求职中心</h1>
            <p className="text-[11.5px] text-ink-faint">看板 · 行动 · 素材 · 跟进 · 复盘 · 统计</p>
          </div>
          <Button variant="ghost" size="icon" className="ml-auto h-[30px] w-[30px]" aria-label="刷新数据"
                  onClick={() => showToast("数据已刷新")}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
        <nav className="mt-2.5 flex gap-1 overflow-x-auto pb-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-[12.5px] transition-colors",
                tab === t.id ? "bg-surface-2 font-[560] text-ink" : "text-ink-faint hover:bg-[var(--hover)] hover:text-ink",
              )}
            >
              <t.icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          ))}
        </nav>
      </header>
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="mx-auto w-full max-w-[1100px]">
          {tab === "board" && <BoardTab onToast={showToast} />}
          {tab === "tasks" && <TasksTab onToast={showToast} opportunities={opportunities} />}
          {tab === "materials" && <MaterialsTab onToast={showToast} />}
          {tab === "followups" && <FollowupsTab onToast={showToast} opportunities={opportunities} />}
          {tab === "offers" && <OffersTab onToast={showToast} opportunities={opportunities} />}
          {tab === "reviews" && <ReviewsTab onToast={showToast} />}
          {tab === "stats" && <StatsTab />}
          {tab === "privacy" && <PrivacyTab onToast={showToast} />}
        </div>
      </div>
      <ToastBubble message={toast} />
    </div>
  )
}
