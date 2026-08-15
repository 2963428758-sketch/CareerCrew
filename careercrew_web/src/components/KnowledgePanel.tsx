import { useEffect, useState, useSyncExternalStore } from "react"
import { Upload, BookOpen, Globe, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip } from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { KB_CATEGORIES, KB_CATEGORY_LABELS } from "@/types"
import { cn } from "@/lib/utils"
import { apiFetch, getAuthSnapshot, subscribeAuth } from "@/lib/auth"

interface KnowledgeDoc {
  doc: string
  source: string
  points: number
  category?: string
  visibility: "private" | "public"
  owner_user_id: string
}

interface KnowledgeStatus {
  points: number
  docs: KnowledgeDoc[]
}

interface UploadJob {
  job_id: string
  filename: string
  status: "queued" | "running" | "done" | "error"
  stage: string
  progress: number
  error?: string | null
  result?: { doc_id?: string; points?: number } | null
}

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中",
  parse: "MinerU 解析文档",
  vectorize: "切分并向量化",
  store: "写入知识库",
  done: "完成",
}

// 各阶段展示进度上限：真实进度只在阶段边界跳跃，阶段内由前端平滑推进，避免进度条长时间"卡住"
const STAGE_CEILING: Record<string, number> = {
  queued: 4,
  parse: 50,
  vectorize: 80,
  store: 95,
}

/** 知识库管理面板（上传 / 列表 / 删除），可嵌入知识库问答页右上角。 */
export default function KnowledgePanel({ onClose }: { onClose?: () => void }) {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot)
  const me = auth.user?.id ?? ""
  const isAdmin = auth.user?.role === "admin"
  const [uploadVisibility, setUploadVisibility] = useState<"private" | "public">("private")
  const [status, setStatus] = useState<KnowledgeStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [files, setFiles] = useState<FileList | null>(null)
  const [uploadCategory, setUploadCategory] = useState("")
  const [uploadError, setUploadError] = useState("")
  const [job, setJob] = useState<UploadJob | null>(null)
  const [displayPct, setDisplayPct] = useState(0)

  const uploading = !!job && (job.status === "queued" || job.status === "running")

  const refresh = () => {
    setLoading(true)
    setError("")
    apiFetch("/api/knowledge")
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => setStatus(d))
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
        const resp = await apiFetch(`/api/knowledge/upload/${jobId}`)
        if (!resp.ok) return
        const next: UploadJob = await resp.json()
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

  const handleUpload = async () => {
    if (!files || files.length === 0) return
    setUploadError("")
    setJob(null)
    setDisplayPct(0)
    const fd = new FormData()
    fd.append("file", files[0])
    fd.append("category", uploadCategory)
    fd.append("visibility", uploadVisibility)
    try {
      const resp = await apiFetch("/api/knowledge/upload", { method: "POST", body: fd })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
      setJob(data as UploadJob)
    } catch (e) {
      setUploadError((e as Error).message)
    }
  }

  /** 待删除确认的文档（自定义 Codex 确认框，替代 window.confirm） */
  const [confirmDoc, setConfirmDoc] = useState<KnowledgeDoc | null>(null)

  const handleDelete = async (doc: KnowledgeDoc) => {
    const resp = await apiFetch(`/api/knowledge/${encodeURIComponent(doc.doc)}`, { method: "DELETE" })
    if (resp.status === 403) {
      setError("只有管理员可以删除公共知识库文档")
      return
    }
    if (!resp.ok) setError(`删除失败：HTTP ${resp.status}`)
    refresh()
  }

  const togglePublish = async (doc: KnowledgeDoc) => {
    const action = doc.visibility === "public" ? "unpublish" : "publish"
    const resp = await apiFetch(`/api/knowledge/${encodeURIComponent(doc.doc)}/${action}`, { method: "POST" })
    if (!resp.ok) { const data = await resp.json().catch(() => ({})); setError(data.detail || `操作失败：HTTP ${resp.status}`); return }
    refresh()
  }

  return (
    <div className="space-y-4">
      {onClose && (
        <div className="flex items-center justify-between">
          <p className="text-[12px] font-medium text-ink-soft">知识库管理</p>
          <Tooltip label="关闭">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} aria-label="关闭">
              <X className="h-4 w-4" />
            </Button>
          </Tooltip>
        </div>
      )}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-[13px] font-medium">上传知识文档</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-nowrap items-center gap-1 overflow-hidden">
            {[{ id: "", label: "自动识别" }, ...KB_CATEGORIES.slice(1)].map((c) => (
              <button
                key={c.id || "auto"}
                onClick={() => setUploadCategory(c.id)}
                className={cn(
                  "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors duration-100",
                  uploadCategory === c.id
                    ? "border-transparent bg-button-ink text-button-onink"
                    : "border-[var(--border-soft)] bg-transparent text-ink-soft hover:bg-[var(--hover)]"
                )}
              >
                {c.label}
              </button>
            ))}
          </div>
          {isAdmin && (
            <div className="flex items-center gap-2">
              <span className="text-[12px] text-ink-soft">可见性</span>
              <button
                onClick={() => setUploadVisibility((v) => (v === "private" ? "public" : "private"))}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors duration-100",
                  uploadVisibility === "public" ? "border-transparent bg-button-ink text-button-onink" : "border-[var(--border-soft)] bg-transparent text-ink-soft hover:bg-[var(--hover)]"
                )}
              >
                {uploadVisibility === "public" ? "发布到公共库" : "我的私有库"}
              </button>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.docx,.pptx,.xlsx,.md,.markdown,.txt"
              onChange={(e) => setFiles(e.target.files)}
              className="h-9 max-w-sm text-[13px]"
            />
            <Button size="sm" className="gap-1.5" onClick={handleUpload} disabled={uploading || !files || files.length === 0}>
              <Upload className="h-3.5 w-3.5" />
              {uploading ? "解析入库中…" : "上传入库"}
            </Button>
          </div>
          <p className="text-[12px] text-ink-soft">
            支持 PDF / 图片 / DOCX / PPTX / XLSX / Markdown / TXT。PDF 与图片会先经 MinerU
            抽取文本再向量化，约需 1-2 分钟，请耐心等待。
          </p>
          {job && job.status !== "error" && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-[12px] text-ink-soft">
                <span>{job.status === "done" ? "完成" : STAGE_LABELS[job.stage] ?? job.stage}</span>
                <span className="tabular-nums">{Math.round(displayPct)}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
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
                <p className="text-[12px] text-ink-faint">PDF / 图片解析较慢，期间进度条会缓慢推进，请勿关闭页面…</p>
              )}
            </div>
          )}
          {job?.status === "done" && displayPct >= 99 && job.result && (
            <p className="text-[12px] font-medium text-green-600">
              ✓ 入库成功：{job.filename} → doc_id={job.result.doc_id}，
              {Number(job.result.points)} 个向量点
            </p>
          )}
          {job?.status === "error" && <p className="text-[12px] font-medium text-destructive">上传失败：{job.error}</p>}
          {uploadError && <p className="text-[12px] font-medium text-destructive">上传失败：{uploadError}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-[13px] font-medium">
            库内文档
            {status && <span className="ml-1 font-normal text-ink-faint">（{status.docs.length} 份）</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-32 w-full" />
          ) : error ? (
            <p className="text-[13px] text-destructive">加载失败：{error}</p>
          ) : !status || status.docs.length === 0 ? (
            <p className="rounded-[8px] border border-dashed border-[var(--border-normal)] px-3 py-6 text-center text-[13px] text-ink-faint">
              知识库为空，先上传一份文档吧
            </p>
          ) : (
            <div className="space-y-3">
              {(() => {
                const publicDocs = status.docs.filter((d) => d.visibility === "public")
                const privateDocs = status.docs.filter((d) => d.visibility !== "public")
                return (
                  <>
                    {publicDocs.length > 0 && (
                      <div>
                        <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium text-amber-600">
                          <Globe className="h-3.5 w-3.5" />
                          公共知识库
                          <span className="font-normal text-ink-faint">（所有人可见 · {publicDocs.length} 份）</span>
                        </p>
                        <div className="space-y-1.5">
                          {publicDocs.map((doc) => <DocRow key={doc.doc + doc.visibility} doc={doc} me={me} isAdmin={isAdmin} onDelete={handleDelete} onTogglePublish={togglePublish} />)}
                        </div>
                      </div>
                    )}
                    {privateDocs.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-[12px] font-medium text-ink-soft">
                          我的资料
                          <span className="ml-1 font-normal text-ink-faint">（仅自己可见 · {privateDocs.length} 份）</span>
                        </p>
                        <div className="space-y-1.5">
                          {privateDocs.map((doc) => <DocRow key={doc.doc + doc.visibility} doc={doc} me={me} isAdmin={isAdmin} onDelete={handleDelete} onTogglePublish={togglePublish} />)}
                        </div>
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function DocRow({ doc, me, isAdmin, onDelete, onTogglePublish }: {
  doc: KnowledgeDoc
  me: string
  isAdmin: boolean
  onDelete: (doc: KnowledgeDoc) => void
  onTogglePublish: (doc: KnowledgeDoc) => void
}) {
  return (
    <div className="flex items-center gap-2 rounded-[8px] border border-[var(--border-soft)] bg-workspace px-3 py-2">
      <BookOpen className="h-4 w-4 shrink-0 text-primary" strokeWidth={1.7} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 truncate text-[13px] font-medium text-ink">
          <span className="truncate">{doc.doc}</span>
          <span className={cn(
            "shrink-0 rounded-[5px] px-1.5 py-0.5 text-[10px] font-medium",
            doc.visibility === "public" ? "bg-amber-500/15 text-amber-600" : "bg-primary/10 text-primary"
          )}>
            {doc.visibility === "public" ? "公共" : "我的"}
          </span>
          {doc.category && (
            <span className="shrink-0 rounded-[5px] bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-soft">
              {KB_CATEGORY_LABELS[doc.category] ?? doc.category}
            </span>
          )}
        </p>
        <p className="truncate text-[11px] text-ink-faint">
          {doc.source.split(/[\\/]/).pop() || doc.source}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {isAdmin && (
          <Tooltip label={doc.visibility === "public" ? "下架公共文档" : "发布到公共库"}>
            <button
              className="flex items-center gap-0.5 rounded-[5px] p-1 text-[11px] text-ink-faint transition-colors duration-100 hover:text-primary"
              onClick={() => onTogglePublish(doc)}
              aria-label={doc.visibility === "public" ? "下架公共文档" : "发布到公共库"}
            >
              <Globe className="h-3.5 w-3.5" />
            </button>
          </Tooltip>
        )}
        {(doc.visibility === "private" ? doc.owner_user_id === me : isAdmin) && (
          <Tooltip label={`删除 ${doc.doc}`}>
            <button
              className="shrink-0 rounded-[5px] p-1 text-ink-faint transition-colors duration-100 hover:text-destructive"
              onClick={() => setConfirmDoc(doc)}
              aria-label={`删除 ${doc.doc}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </Tooltip>
        )}
      </div>
    </div>
  )
}
