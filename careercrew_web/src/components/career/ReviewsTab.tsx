import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { networkErrorText } from "@/lib/errors"
import { createRealInterview, deleteRealInterview, listInterviewReports, listRealInterviews, type InterviewReport, type RealInterviewRecord } from "@/lib/career"
import { DATE_HINT } from "./dates"

export function ReviewsTab({ onToast }: { onToast: (m: string) => void }) {
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

// ── 联系人与内推 ──
