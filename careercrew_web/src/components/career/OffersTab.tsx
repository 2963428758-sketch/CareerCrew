import { useEffect, useState } from "react"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { EmptyState } from "@/components/workspace/EmptyState"
import { networkErrorText } from "@/lib/errors"
import { createOffer, deleteOffer, listOffers, type BoardRow, type Offer } from "@/lib/career"
import { cn } from "@/lib/utils"

const OFFER_WEIGHTS = [
  { key: "base_salary", label: "薪资" },
  { key: "location", label: "地点" },
  { key: "work_mode", label: "工作方式" },
  { key: "growth", label: "成长" },
] as const

export function OffersTab({ onToast, opportunities }: { onToast: (m: string) => void; opportunities: BoardRow[] }) {
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
