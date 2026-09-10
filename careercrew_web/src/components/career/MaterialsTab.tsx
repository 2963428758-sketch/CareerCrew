import { useEffect, useState } from "react"
import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/workspace/EmptyState"
import { networkErrorText } from "@/lib/errors"
import { createMaterial, deleteMaterial, listMaterials, updateMaterial, type Material } from "@/lib/career"
import { cn } from "@/lib/utils"

const EMPTY_MATERIAL = { name: "", background: "", role: "", actions: "", results: "", tags: "" }

export function MaterialsTab({ onToast }: { onToast: (m: string) => void }) {
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
