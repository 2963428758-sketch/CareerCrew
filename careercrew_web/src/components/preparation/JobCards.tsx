import { useState } from "react"
import { Link } from "react-router-dom"
import { BookmarkCheck, BookmarkPlus, ChevronDown, ChevronUp, ExternalLink } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { collectOpportunity, isSafeHttpUrl } from "@/lib/preparation"
import { networkErrorText } from "@/lib/errors"
import type { JobOpportunity } from "@/types"

/**
 * 匹配回答下方的结构化岗位卡片（仅来自成功 search_jobs 工具的结构化结果，
 * 绝不解析 LLM 正文）。收藏动作把该岗位写入"岗位准备"，自动携带 JD 快照。
 */
function JobCard({ job }: { job: JobOpportunity }) {
  const [expandJd, setExpandJd] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedId, setSavedId] = useState<string | null>(null)
  const [error, setError] = useState("")

  const safeUrl = isSafeHttpUrl(job.url)
  const handleCollect = async () => {
    if (saving || savedId) return
    setSaving(true)
    setError("")
    try {
      const saved = await collectOpportunity(job)
      setSavedId(saved.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : networkErrorText(e, "收藏失败，请稍后重试"))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-[10px] border border-[var(--border-soft)] bg-card p-3.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-[560] text-ink">{job.company}</span>
        <span className="text-ink">· {job.title}</span>
        {job.salary && <span className="text-ink-soft">{job.salary}</span>}
        {job.city && <span className="text-ink-soft">{job.city}</span>}
        {job.retrieval_mode_label && (
          <Badge variant="outline" className="text-[10.5px]">{job.retrieval_mode_label}</Badge>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11.5px] text-ink-faint">
        {job.source_label && <span>来源：{job.source_label}</span>}
        {job.experience && <span>经验：{job.experience}</span>}
        {safeUrl && (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="inline-flex items-center gap-0.5 hover:text-ink"
            onClick={(e) => e.stopPropagation()}
          >
            来源链接 <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {job.jd ? (
        <div className="mt-2 text-[12.5px] leading-relaxed text-ink-soft">
          <p className={expandJd ? "whitespace-pre-wrap break-words" : "line-clamp-2 whitespace-pre-wrap break-words"}>
            {job.jd}
          </p>
          <button
            type="button"
            className="mt-1 inline-flex items-center gap-0.5 text-[11.5px] text-ink-faint hover:text-ink"
            onClick={() => setExpandJd((v) => !v)}
          >
            {expandJd ? <>收起 JD <ChevronUp className="h-3 w-3" /></> : <>展开 JD <ChevronDown className="h-3 w-3" /></>}
          </button>
        </div>
      ) : (
        <p className="mt-2 text-[12px] text-ink-faint">
          暂无 JD 全文：请打开来源链接复制 JD，再通过「岗位准备 → 手动录入岗位」保存。
        </p>
      )}

      <div className="mt-2.5 flex items-center gap-2">
        {savedId ? (
          <>
            <span className="inline-flex items-center gap-1 text-[12px] text-emerald-600">
              <BookmarkCheck className="h-3.5 w-3.5" /> 已收藏
            </span>
            <Button asChild variant="outline" size="sm" className="h-[26px] text-[12px]">
              <Link to={`/preparation?opportunity=${encodeURIComponent(savedId)}`}>去准备</Link>
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="h-[26px] text-[12px]"
            disabled={saving || !job.jd}
            title={!job.jd ? "缺少 JD 全文，请先手动录入" : undefined}
            onClick={handleCollect}
          >
            <BookmarkPlus className="h-3.5 w-3.5" /> {saving ? "收藏中…" : "收藏岗位"}
          </Button>
        )}
        {error && <span className="text-[11.5px] text-destructive">{error}</span>}
      </div>
    </div>
  )
}

export function JobCards({ jobs }: { jobs: JobOpportunity[] }) {
  if (!jobs.length) return null
  return (
    <div className="mt-2 flex flex-col gap-2" data-testid="job-cards">
      {jobs.map((job, i) => (
        <JobCard key={`${job.source}-${job.url || job.company}-${i}`} job={job} />
      ))}
    </div>
  )
}
