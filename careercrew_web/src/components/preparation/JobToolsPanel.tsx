import { useCallback, useEffect, useState } from "react"
import { BookOpenCheck, Copy, Loader2, ScanSearch, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { networkErrorText } from "@/lib/errors"
import {
  createApplicationKit, createIntelBrief, runAtsCheck,
  type ApplicationKit, type AtsResult, type IntelBrief } from "@/lib/career"
import { listVersions, type Opportunity, type ResumeVersion } from "@/lib/preparation"

const ATS_STATUS: Record<string, { label: string; className: string }> = {
  pass: { label: "通过", className: "text-emerald-600" },
  warn: { label: "建议改进", className: "text-amber-600" },
}

/**
 * 求职工具箱：基于选定简历版本做四件事——
 * 1. ATS 体检（确定性规则：联系方式/章节/时间线/量化/篇幅/JD 覆盖，非 AI）；
 * 2. 投递材料包（LLM 生成求职信/自我介绍/招呼语/跟进话术/感谢信，模板兜底；仅草稿）；
 * 3. 面试情报包（公司推断/可能问题/待确认问题；外部事实标注需自行核实）；
 * 4. 结果可复制/保存为素材。
 */
export function JobToolsPanel({ opportunity, onToast }: {
  opportunity: Opportunity
  onToast: (msg: string) => void
}) {
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [versionId, setVersionId] = useState("")
  const [ats, setAts] = useState<AtsResult | null>(null)
  const [kit, setKit] = useState<ApplicationKit | null>(null)
  const [brief, setBrief] = useState<IntelBrief | null>(null)
  const [running, setRunning] = useState<"ats" | "kit" | "brief" | null>(null)
  const [error, setError] = useState("")

  const reloadVersions = useCallback(async () => {
    try {
      const rows = await listVersions(opportunity.id)
      setVersions(rows)
      if (rows.length > 0) setVersionId((prev) => prev || rows[0].id)
    } catch (e) {
      setError(networkErrorText(e, "版本加载失败"))
    }
  }, [opportunity.id])

  useEffect(() => {
    void reloadVersions()
    const onVersionsChanged = () => { void reloadVersions() }
    window.addEventListener("preparation:versions-changed", onVersionsChanged)
    return () => window.removeEventListener("preparation:versions-changed", onVersionsChanged)
  }, [reloadVersions])

  const runAts = async () => {
    if (running) return
    setRunning("ats")
    setError("")
    try {
      setAts(await runAtsCheck(opportunity.id, versionId))
    } catch (e) {
      setError(networkErrorText(e, "体检失败，请稍后重试"))
    } finally {
      setRunning(null)
    }
  }

  const runKit = async () => {
    if (running) return
    setRunning("kit")
    setError("")
    try {
      setKit(await createApplicationKit(opportunity.id, versionId))
      onToast("材料包草稿已生成，发送前请确认内容")
    } catch (e) {
      setError(networkErrorText(e, "生成失败，请稍后重试"))
    } finally {
      setRunning(null)
    }
  }

  const runBrief = async () => {
    if (running) return
    setRunning("brief")
    setError("")
    try {
      setBrief(await createIntelBrief(opportunity.id, versionId))
      onToast("情报包已生成，外部事实请自行核实")
    } catch (e) {
      setError(networkErrorText(e, "生成失败，请稍后重试"))
    } finally {
      setRunning(null)
    }
  }

  const copySection = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      onToast("已复制")
    } catch {
      onToast("复制失败，请手动选择文本复制")
    }
  }

  const saveKitAsMaterial = async () => {
    if (!kit) return
    try {
      const { createMaterial } = await import("@/lib/career")
      await createMaterial({
        name: `投递材料包 · ${opportunity.company}`,
        background: `为「${opportunity.company} · ${opportunity.title}」生成的投递材料草稿（${kit.source === "llm" ? "AI 生成" : "模板"}，发送前需人工确认）`,
        results: Object.entries(kit.sections)
          .map(([key, value]) => value && `【${KIT_LABELS[key] ?? key}】\n${value}`)
          .filter(Boolean)
          .join("\n\n"),
        tags: ["投递材料", opportunity.company],
        confirmed: false,
      })
      onToast("已保存到素材库（标记为未确认草稿）")
    } catch (e) {
      onToast(networkErrorText(e, "保存失败，请稍后重试"))
    }
  }

  return (
    <div className="flex flex-col gap-2.5" data-testid="job-tools">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13.5px] font-[560] text-ink">求职工具箱</h3>
        <select
          value={versionId}
          onChange={(e) => setVersionId(e.target.value)}
          aria-label="选择简历版本"
          className="h-[28px] rounded-[7px] border border-[var(--border-soft)] bg-workspace px-2 text-[12px] text-ink"
        >
          {versions.length === 0 && <option value="">（先保存一个简历版本）</option>}
          {versions.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <Button size="sm" variant="outline" className="h-[26px] text-[12px]"
                disabled={!versionId || running !== null} onClick={() => void runAts()}>
          {running === "ats" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ScanSearch className="h-3.5 w-3.5" />}
          ATS 体检
        </Button>
        <Button size="sm" variant="outline" className="h-[26px] text-[12px]"
                disabled={!versionId || running !== null} onClick={() => void runKit()}>
          {running === "kit" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          生成投递材料包
        </Button>
        <Button size="sm" variant="outline" className="h-[26px] text-[12px]"
                disabled={running !== null} onClick={() => void runBrief()}>
          {running === "brief" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookOpenCheck className="h-3.5 w-3.5" />}
          面试情报包
        </Button>
      </div>

      {error && <p className="text-[12px] text-destructive">{error}</p>}

      {ats && (
        <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
          <p className="flex items-center gap-1.5 font-[560] text-ink">
            ATS 体检
            <Badge variant="outline" className="text-[10.5px]">规则检查 · 非 AI</Badge>
          </p>
          {ats.jd_coverage && (
            <p className="mt-1 text-ink-soft">
              JD 关键要求覆盖：{ats.jd_coverage.covered}/{ats.jd_coverage.requirements}
            </p>
          )}
          <ul className="mt-1.5 flex flex-col gap-1">
            {ats.checks.map((c, i) => {
              const meta = ATS_STATUS[c.status] ?? { label: c.status, className: "text-ink-faint" }
              return (
                <li key={i} className="flex flex-wrap items-center gap-x-2">
                  <span className="font-[520] text-ink">{c.item}</span>
                  <span className={meta.className}>{meta.label}</span>
                  {c.note && <span className="text-ink-faint">{c.note}</span>}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {kit && (
        <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
          <div className="flex items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 font-[560] text-ink">
              投递材料包
              <Badge variant="outline" className="text-[10.5px]">
                {kit.source === "llm" ? "AI 生成草稿" : "模板草稿"}
              </Badge>
            </p>
            <Button size="sm" variant="ghost" className="h-[24px] px-2 text-[11.5px]" onClick={() => void saveKitAsMaterial()}>
              保存为素材
            </Button>
          </div>
          {Object.entries(kit.sections).map(([key, value]) => (
            value ? (
              <div key={key} className="mt-2">
                <div className="flex items-center justify-between">
                  <p className="font-[520] text-ink-soft">{KIT_LABELS[key] ?? key}</p>
                  <button type="button" className="inline-flex items-center gap-0.5 text-[11px] text-ink-faint hover:text-ink"
                          onClick={() => void copySection(value)}>
                    <Copy className="h-3 w-3" /> 复制
                  </button>
                </div>
                <p className="mt-0.5 whitespace-pre-wrap break-words text-ink">{value}</p>
              </div>
            ) : null
          ))}
          <p className="mt-2 text-[11px] text-ink-faint">所有话术均为草稿；实际发送前请逐条确认并按需修改。</p>
        </div>
      )}

      {brief && (
        <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[12.5px]">
          <p className="flex items-center gap-1.5 font-[560] text-ink">
            面试情报包
            <Badge variant="outline" className="text-[10.5px]">
              {brief.source === "llm" ? "AI 生成" : "模板生成"}
            </Badge>
          </p>
          <p className="mt-1 text-ink-soft">{brief.company_research}</p>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <div>
              <p className="font-[520] text-ink">可能的问题</p>
              <ul className="mt-0.5 list-inside list-disc text-ink-soft">
                {brief.likely_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </div>
            <div>
              <p className="font-[520] text-ink">待向面试官确认</p>
              <ul className="mt-0.5 list-inside list-disc text-ink-soft">
                {brief.confirm_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </div>
          </div>
          {brief.evidence.length > 0 && (
            <p className="mt-1.5 text-ink-soft">可用证据：{brief.evidence.join("；")}</p>
          )}
          <p className="mt-2 text-[11px] text-amber-600">{brief.disclaimer}</p>
        </div>
      )}
    </div>
  )
}

const KIT_LABELS: Record<string, string> = {
  cover_letter: "求职信",
  self_intro: "自我介绍（30 秒）",
  greeting: "Boss 招呼语",
  followup: "HR 跟进话术",
  thank_you: "面试后感谢信",
}
