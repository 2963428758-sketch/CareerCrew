import { useEffect, useRef, useState } from "react"
import { Upload, FileText, Trash2, RefreshCw, Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  fetchResumeContent,
  type ActiveResume,
  type ResumeLibraryItem,
  type ResumeUploadJob,
} from "@/lib/resumeUpload"
import { apiFetch } from "@/lib/auth"

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中",
  parse: "解析简历",
  done: "完成",
}

// 各阶段展示进度上限：真实进度只在阶段边界跳跃，阶段内由前端平滑推进，避免进度条长时间"卡住"
const STAGE_CEILING: Record<string, number> = {
  queued: 4,
  parse: 95,
}

interface ResumePanelProps {
  onClose?: () => void
  /** 解析完成 / 点「用于当前对话」时回调，携带可用于当前会话的简历内容 */
  onActive?: (resume: ActiveResume) => void
}

/** 简历管理面板（上传解析 + 我的简历列表），可嵌入简历优化页右上角抽屉。 */
export default function ResumePanel({ onClose, onActive }: ResumePanelProps) {
  const [resumes, setResumes] = useState<ResumeLibraryItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [files, setFiles] = useState<FileList | null>(null)
  const [uploadError, setUploadError] = useState("")
  const [job, setJob] = useState<ResumeUploadJob | null>(null)
  const [displayPct, setDisplayPct] = useState(0)
  /** 正在读取某份简历内容用于当前对话 */
  const [activatingId, setActivatingId] = useState<string | null>(null)
  /** 已回调 onActive 的任务 id：避免父组件重渲染时重复触发（重复添加附件气泡） */
  const firedJobRef = useRef<string | null>(null)

  const uploading = !!job && (job.status === "queued" || job.status === "running")

  const refresh = () => {
    setLoading(true)
    setError("")
    apiFetch("/api/resume/library")
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d: { resumes: ResumeLibraryItem[] }) => setResumes(d.resumes))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  // 任务进行中：每秒轮询一次真实进度
  const jobId = job?.job_id
  const jobStatus = job?.status
  useEffect(() => {
    if (!jobId || jobStatus === "done" || jobStatus === "error") return
    const timer = setInterval(async () => {
      try {
        const resp = await apiFetch(`/api/resume/upload/${jobId}`)
        if (!resp.ok) return
        const next: ResumeUploadJob = await resp.json()
        setJob(next)
        if (next.status === "done") {
          setFiles(null)
          refresh()
        }
      } catch {
        // 单次轮询失败可忽略，下个周期重试
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [jobId, jobStatus])

  // 展示进度：阶段内缓慢推进，阶段切换时向真实进度平滑滑行（不瞬间跳变）；
  // 完成后继续滑到 100%，避免"进度条还在半途就显示已完成"
  const jobStage = job?.stage
  const jobProgress = job?.progress
  useEffect(() => {
    if (!jobId || jobStatus === "error") return
    const ceiling = jobStatus === "done" ? 100 : STAGE_CEILING[jobStage ?? ""] ?? 95
    const realPct = jobStatus === "done" ? 100 : Math.min(Math.round((jobProgress ?? 0) * 100), 100)
    const timer = setInterval(() => {
      setDisplayPct((prev) => {
        if (jobStatus === "done") {
          // 完成：快速滑到 100 并定格
          return prev >= 98.5 ? 100 : Math.min(prev + (100 - prev) * 0.5, 100)
        }
        // 正常阶段：至少缓慢前进；真实进度跳到前面时按比例滑行追赶
        const minStep = Math.min(ceiling, prev + 0.2)
        const desired = Math.max(realPct, minStep)
        return Math.min(Math.max(prev + (desired - prev) * 0.4, minStep), 100)
      })
    }, 400)
    return () => clearInterval(timer)
  }, [jobId, jobStatus, jobStage, jobProgress])

  // 上传完成：把解析结果直接用于当前会话（每个任务只回调一次）
  useEffect(() => {
    if (job?.status === "done" && job.result && onActive && firedJobRef.current !== job.job_id) {
      firedJobRef.current = job.job_id
      onActive({
        resume_id: job.result.resume_id,
        filename: job.result.filename,
        doc_type: job.result.doc_type,
        char_count: job.result.char_count,
        content: job.result.content,
      })
    }
  }, [job, onActive])

  const handleUpload = async () => {
    if (!files || files.length === 0) return
    setUploadError("")
    setJob(null)
    setDisplayPct(0)
    const fd = new FormData()
    fd.append("file", files[0])
    try {
      const resp = await apiFetch("/api/resume/upload", { method: "POST", body: fd })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
      setJob(data as ResumeUploadJob)
    } catch (e) {
      setUploadError((e as Error).message)
    }
  }

  const handleActivate = async (item: ResumeLibraryItem) => {
    if (!onActive) return
    setActivatingId(item.resume_id)
    try {
      const content = await fetchResumeContent(item.resume_id)
      onActive({
        resume_id: item.resume_id,
        filename: item.filename,
        doc_type: item.doc_type,
        char_count: item.char_count,
        content,
      })
    } catch (e) {
      setUploadError(`读取简历失败：${(e as Error).message}`)
    } finally {
      setActivatingId(null)
    }
  }

  const handleDelete = async (item: ResumeLibraryItem) => {
    if (!window.confirm(`确定从简历库删除「${item.filename}」吗？删除后需重新上传才能恢复。`)) return
    try {
      const resp = await apiFetch(`/api/resume/library/${encodeURIComponent(item.resume_id)}`, {
        method: "DELETE",
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      refresh()
    } catch (e) {
      setUploadError(`删除失败：${(e as Error).message}`)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">上传简历</CardTitle>
            {onClose && (
              <button
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={onClose}
                title="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.gif,.bmp,.webp,.txt,.md,.markdown,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
              onChange={(e) => setFiles(e.target.files)}
              className="h-9 max-w-sm text-sm"
            />
            <Button size="sm" className="gap-1.5" onClick={handleUpload} disabled={uploading || !files || files.length === 0}>
              <Upload className="h-3.5 w-3.5" />
              {uploading ? "解析中…" : "上传解析"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            支持 PDF / 图片 / TXT / MD / DOCX 等 · 最大 20MB。PDF 与图片会先经 MinerU
            抽取文本，约需 1-2 分钟，请耐心等待。
          </p>
          {job && job.status !== "error" && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{job.status === "done" ? "完成" : STAGE_LABELS[job.stage] ?? job.stage}</span>
                <span className="tabular-nums">{Math.round(displayPct)}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={
                    job.status === "done"
                      ? "h-full rounded-full bg-green-600 transition-[width] duration-300 ease-out"
                      : "h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
                  }
                  style={{ width: `${displayPct}%` }}
                />
              </div>
              {job.status !== "done" && job.stage === "parse" && (
                <p className="text-xs text-muted-foreground">PDF / 图片解析较慢，期间进度条会缓慢推进，请勿关闭页面…</p>
              )}
            </div>
          )}
          {job?.status === "done" && displayPct >= 99 && job.result && (
            <p className="text-xs font-medium text-green-600">
              ✓ 解析成功：{job.result.filename}（{job.result.doc_type} · {job.result.char_count} 字符）
            </p>
          )}
          {job?.status === "error" && <p className="text-xs font-medium text-destructive">解析失败：{job.error}</p>}
          {uploadError && <p className="text-xs font-medium text-destructive">操作失败：{uploadError}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">
              我的简历
              {resumes && <span className="ml-1 font-normal text-muted-foreground">（{resumes.length} 份）</span>}
            </CardTitle>
            <button
              className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              onClick={refresh}
              title="刷新"
            >
              <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            </button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-32 w-full" />
          ) : error ? (
            <p className="text-sm text-destructive">加载失败：{error}</p>
          ) : !resumes || resumes.length === 0 ? (
            <p className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
              还没有上传过简历，先上传一份吧
            </p>
          ) : (
            <div className="space-y-1.5">
              {resumes.map((item) => (
                <div key={item.resume_id} className="flex items-center gap-2 rounded-md border bg-card px-3 py-2">
                  <FileText className="h-4 w-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{item.filename}</p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {item.doc_type} · {item.char_count} 字符
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0 gap-1 px-2 text-[11px]"
                    onClick={() => handleActivate(item)}
                    disabled={activatingId === item.resume_id}
                  >
                    {activatingId === item.resume_id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Upload className="h-3 w-3" />
                    )}
                    用于当前对话
                  </Button>
                  <button
                    className="shrink-0 text-muted-foreground transition-colors hover:text-destructive"
                    onClick={() => handleDelete(item)}
                    title={`删除 ${item.filename}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
