import { useEffect, useState, useSyncExternalStore } from "react"
import { BookOpen, ChevronDown, Edit3, Globe, RefreshCw, Save, Settings2, Trash2, Upload, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip } from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { KB_CATEGORIES, KB_CATEGORY_LABELS } from "@/types"
import { cn } from "@/lib/utils"
import { apiFetch, getAuthSnapshot, subscribeAuth } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

interface KnowledgeDoc {
  doc: string
  doc_name?: string
  title?: string
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

interface KnowledgeGovernanceChunk {
  id: string
  ordinal: number
  page?: number | null
  text?: string
  index_status?: string
  updated_at?: string | null
}

interface KnowledgeChunkPatch {
  text: string
  page: number | null
  updated_at?: string | null
}

interface KnowledgeGovernanceVersion {
  id: string
  version_number: number
  status: string
  expires_at?: string | null
  credibility?: number | null
  indexed_at?: string | null
  citation_hits?: number
  chunks?: KnowledgeGovernanceChunk[]
}

interface KnowledgeGovernanceDoc {
  id: string
  owner_id?: string
  name: string
  category?: string
  visibility?: "private" | "public"
  status: string
  active_version_id?: string | null
  expires_at?: string | null
  credibility?: number | null
  citation_hits?: number
  versions: KnowledgeGovernanceVersion[]
}

interface KnowledgeGovernanceResponse {
  items: KnowledgeGovernanceDoc[]
  total: number
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

const GOVERNANCE_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  indexing: "索引中",
  active: "生效中",
  archived: "已归档",
  failed: "索引失败",
  expired: "已过期",
}

const INDEX_STATUS_LABELS: Record<string, string> = {
  pending: "待索引",
  indexed: "已索引",
  failed: "索引失败",
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
  const [governanceOpen, setGovernanceOpen] = useState(false)
  const [governanceDocs, setGovernanceDocs] = useState<KnowledgeGovernanceDoc[] | null>(null)
  const [governanceLoading, setGovernanceLoading] = useState(false)
  const [governanceError, setGovernanceError] = useState("")
  const [governanceBusy, setGovernanceBusy] = useState("")

  const uploading = !!job && (job.status === "queued" || job.status === "running")

  const refresh = () => {
    setLoading(true)
    setError("")
    apiFetch("/api/knowledge")
      .then(async (r) => {
        if (!r.ok) throw new Error(await apiErrorText(r, "加载知识库失败"))
        return r.json()
      })
      .then((d) => setStatus(d))
      .catch((e) => setError(networkErrorText(e, "网络连接失败，请检查网络后重试")))
      .finally(() => setLoading(false))
  }

  const loadGovernance = async () => {
    setGovernanceLoading(true)
    setGovernanceError("")
    try {
      const resp = await apiFetch("/api/knowledge/governance/documents")
      if (!resp.ok) throw new Error(await apiErrorText(resp, "加载知识治理失败"))
      const body = await resp.json() as KnowledgeGovernanceResponse
      setGovernanceDocs(Array.isArray(body.items) ? body.items : [])
      return true
    } catch (e) {
      setGovernanceError(networkErrorText(e, "网络连接失败，请检查网络后重试"))
      return false
    } finally {
      setGovernanceLoading(false)
    }
  }

  const toggleGovernance = () => {
    const nextOpen = !governanceOpen
    setGovernanceOpen(nextOpen)
    if (nextOpen && governanceDocs === null) void loadGovernance()
  }

  const saveGovernance = async (doc: KnowledgeGovernanceDoc, values: { expires_at: string | null; credibility: number }) => {
    setGovernanceBusy(`save:${doc.id}`)
    setGovernanceError("")
    try {
      const resp = await apiFetch(`/api/knowledge/governance/documents/${encodeURIComponent(doc.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "保存知识治理设置失败"))
      await loadGovernance()
    } catch (e) {
      setGovernanceError(networkErrorText(e, "保存失败，请稍后重试"))
    } finally {
      setGovernanceBusy("")
    }
  }

  const reindexGovernance = async (doc: KnowledgeGovernanceDoc, version: KnowledgeGovernanceVersion) => {
    setGovernanceBusy(`reindex:${doc.id}:${version.id}`)
    setGovernanceError("")
    try {
      const resp = await apiFetch(
        `/api/knowledge/governance/documents/${encodeURIComponent(doc.id)}/versions/${encodeURIComponent(version.id)}/reindex`,
        { method: "POST" },
      )
      if (!resp.ok) throw new Error(await apiErrorText(resp, "重新索引失败"))
      await loadGovernance()
    } catch (e) {
      setGovernanceError(networkErrorText(e, "重新索引失败，请稍后重试"))
    } finally {
      setGovernanceBusy("")
    }
  }

  const saveGovernanceChunk = async (
    doc: KnowledgeGovernanceDoc,
    version: KnowledgeGovernanceVersion,
    chunk: KnowledgeGovernanceChunk,
    values: KnowledgeChunkPatch,
  ): Promise<boolean> => {
    setGovernanceBusy(`chunk:${doc.id}:${version.id}:${chunk.id}`)
    setGovernanceError("")
    try {
      const resp = await apiFetch(
        `/api/knowledge/governance/documents/${encodeURIComponent(doc.id)}/versions/${encodeURIComponent(version.id)}/chunks/${encodeURIComponent(chunk.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(values),
        },
      )
      if (!resp.ok) throw new Error(await apiErrorText(resp, "保存分块失败"))
      return await loadGovernance()
    } catch (e) {
      setGovernanceError(networkErrorText(e, "保存分块失败，请刷新后重试"))
      return false
    } finally {
      setGovernanceBusy("")
    }
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
      if (!resp.ok) throw new Error(await apiErrorText(resp, "上传失败，请重试"))
      const data = await resp.json()
      setJob(data as UploadJob)
    } catch (e) {
      setUploadError(networkErrorText(e, "上传失败，请检查网络后重试"))
    }
  }

  /** 待删除确认的文档（自定义 Codex 确认框，替代 window.confirm） */
  const [confirmDoc, setConfirmDoc] = useState<KnowledgeDoc | null>(null)

  const handleDelete = async (doc: KnowledgeDoc) => {
    try {
      const resp = await apiFetch(`/api/knowledge/${encodeURIComponent(doc.doc)}`, { method: "DELETE" })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "删除文档失败"))
      refresh()
    } catch (e) {
      setError(`删除失败：${networkErrorText(e, "网络连接失败，请重试")}`)
    }
  }

  const togglePublish = async (doc: KnowledgeDoc) => {
    const action = doc.visibility === "public" ? "unpublish" : "publish"
    try {
      const resp = await apiFetch(`/api/knowledge/${encodeURIComponent(doc.doc)}/${action}`, { method: "POST" })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "操作失败"))
      refresh()
    } catch (e) {
      setError(networkErrorText(e, "操作失败，请检查网络后重试"))
    }
  }

  return (
    <div className="space-y-4">
      <ConfirmDialog
        open={confirmDoc !== null}
        title="从知识库删除？"
        message={`「${confirmDoc?.doc ?? ""}」删除后需重新上传才能恢复。`}
        onConfirm={() => confirmDoc && void handleDelete(confirmDoc)}
        onClose={() => setConfirmDoc(null)}
      />
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-[13px] font-medium">知识治理</CardTitle>
              <p className="mt-1 text-[12px] font-normal text-ink-faint">
                管理文档版本、分块索引、失效日期、可信度和引用命中；与传统上传列表保持兼容。
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="min-h-11 gap-1.5"
              onClick={toggleGovernance}
              aria-expanded={governanceOpen}
              aria-controls="knowledge-governance-panel"
            >
              <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
              {governanceOpen ? "收起知识治理" : "打开知识治理"}
            </Button>
          </div>
        </CardHeader>
        {governanceOpen && (
          <CardContent id="knowledge-governance-panel" className="space-y-3">
            {governanceLoading && !governanceDocs ? (
              <Skeleton className="h-32 w-full" />
            ) : governanceDocs ? (
              <div className="space-y-2">
                {governanceError && (
                  <div className="space-y-2 rounded-[8px] border border-destructive/30 bg-destructive/5 p-3">
                    <p className="text-[13px] text-destructive">知识治理加载失败：{governanceError}</p>
                    <Button type="button" variant="outline" size="sm" className="min-h-11 gap-1.5" onClick={() => void loadGovernance()}>
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                      重试知识治理
                    </Button>
                  </div>
                )}
                {governanceDocs.length === 0 ? (
                  <p className="rounded-[8px] border border-dashed border-[var(--border-normal)] px-3 py-6 text-center text-[13px] text-ink-faint">
                    暂无进入治理生命周期的文档。传统上传文档不会自动伪装成治理文档。
                  </p>
                ) : (
                  governanceDocs.map((doc) => (
                    <KnowledgeGovernanceRow
                      key={doc.id}
                      doc={doc}
                      busy={governanceBusy}
                      canGovern={isAdmin || doc.owner_id === me}
                      onSave={saveGovernance}
                      onReindex={reindexGovernance}
                      onChunkSave={saveGovernanceChunk}
                    />
                  ))
                )}
              </div>
            ) : governanceError ? (
              <div className="space-y-2 rounded-[8px] border border-destructive/30 bg-destructive/5 p-3">
                <p className="text-[13px] text-destructive">知识治理加载失败：{governanceError}</p>
                <Button type="button" variant="outline" size="sm" className="min-h-11 gap-1.5" onClick={() => void loadGovernance()}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  重试知识治理
                </Button>
              </div>
            ) : null}
          </CardContent>
        )}
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
                          {publicDocs.map((doc) => <DocRow key={doc.doc + doc.visibility} doc={doc} me={me} isAdmin={isAdmin} onDelete={(d) => setConfirmDoc(d)} onTogglePublish={togglePublish} />)}
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
                          {privateDocs.map((doc) => <DocRow key={doc.doc + doc.visibility} doc={doc} me={me} isAdmin={isAdmin} onDelete={(d) => setConfirmDoc(d)} onTogglePublish={togglePublish} />)}
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
  const displayName = doc.title || doc.doc_name || doc.source.split(/[\\/]/).pop() || doc.doc
  return (
    <div className="flex items-center gap-2 rounded-[8px] border border-[var(--border-soft)] bg-workspace px-3 py-2">
      <BookOpen className="h-4 w-4 shrink-0 text-primary" strokeWidth={1.7} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 truncate text-[13px] font-medium text-ink">
          <span className="truncate" title={displayName}>{displayName}</span>
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
          ID: {doc.doc} · {doc.points} 向量点
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
              onClick={() => onDelete(doc)}
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

function KnowledgeGovernanceRow({
  doc,
  busy,
  canGovern,
  onSave,
  onReindex,
  onChunkSave,
}: {
  doc: KnowledgeGovernanceDoc
  busy: string
  canGovern: boolean
  onSave: (doc: KnowledgeGovernanceDoc, values: { expires_at: string | null; credibility: number }) => Promise<void>
  onReindex: (doc: KnowledgeGovernanceDoc, version: KnowledgeGovernanceVersion) => Promise<void>
  onChunkSave: (doc: KnowledgeGovernanceDoc, version: KnowledgeGovernanceVersion, chunk: KnowledgeGovernanceChunk, values: KnowledgeChunkPatch) => Promise<boolean>
}) {
  const [expiresAt, setExpiresAt] = useState(doc.expires_at?.slice(0, 10) ?? "")
  const [credibility, setCredibility] = useState(String(doc.credibility ?? 1))
  const parsedCredibility = Number(credibility)
  const validCredibility = Number.isFinite(parsedCredibility) && parsedCredibility >= 0 && parsedCredibility <= 1
  const saving = busy === `save:${doc.id}`
  const versions = doc.versions ?? []
  const [editingChunk, setEditingChunk] = useState<{ id: string; text: string; page: string } | null>(null)
  const [expandedVersions, setExpandedVersions] = useState<Record<string, boolean>>({})

  useEffect(() => {
    setExpiresAt(doc.expires_at?.slice(0, 10) ?? "")
    setCredibility(String(doc.credibility ?? 1))
  }, [doc.credibility, doc.expires_at, doc.id])

  const startChunkEdit = (chunk: KnowledgeGovernanceChunk) => {
    setEditingChunk({
      id: chunk.id,
      text: chunk.text || "",
      page: chunk.page == null ? "" : String(chunk.page),
    })
  }

  const saveChunk = async (version: KnowledgeGovernanceVersion, chunk: KnowledgeGovernanceChunk) => {
    if (!editingChunk || editingChunk.id !== chunk.id) return
    const pageText = editingChunk.page.trim()
    const page = pageText ? Number(pageText) : null
    if (!editingChunk.text.trim() || (page !== null && (!Number.isInteger(page) || page < 1))) return
    const saved = await onChunkSave(doc, version, chunk, {
      text: editingChunk.text,
      page,
      updated_at: chunk.updated_at ?? null,
    })
    if (saved) setEditingChunk(null)
  }

  return (
    <article className="rounded-[8px] border border-[var(--border-soft)] bg-workspace p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium text-ink" title={doc.name}>{doc.name}</p>
            <p className="mt-1 text-[11px] text-ink-faint">
              {GOVERNANCE_STATUS_LABELS[doc.status] ?? doc.status} · {versions.length} 个版本 · 引用命中 {doc.citation_hits ?? 0}
              {doc.category ? ` · ${doc.category}` : ""}
            </p>
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
          {doc.visibility === "public" ? "公共" : "私有"}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
        <label className="space-y-1 text-[11px] text-ink-soft">
          <span className="block">可信度（0-1）</span>
          <input
            type="number"
            min="0"
            max="1"
            step="0.1"
            value={credibility}
            onChange={(event) => setCredibility(event.target.value)}
            disabled={!canGovern}
            aria-label={`可信度 ${doc.name}`}
            className="min-h-11 w-full rounded-[7px] border border-input bg-card px-2.5 text-[13px] text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </label>
        <label className="space-y-1 text-[11px] text-ink-soft">
          <span className="block">失效日期（留空不修改）</span>
          <input
            type="date"
            value={expiresAt}
            onChange={(event) => setExpiresAt(event.target.value)}
            disabled={!canGovern}
            aria-label={`失效日期 ${doc.name}`}
            className="min-h-11 w-full rounded-[7px] border border-input bg-card px-2.5 text-[13px] text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-h-11 gap-1.5"
          onClick={() => void onSave(doc, { expires_at: expiresAt || null, credibility: parsedCredibility })}
          disabled={!canGovern || busy !== "" || !validCredibility}
          aria-label={`保存治理设置 ${doc.name}`}
        >
          <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
          {saving ? "保存中…" : "保存设置"}
        </Button>
      </div>

      <details className="mt-3 border-t border-[var(--border-soft)] pt-2.5">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12px] font-medium text-primary">
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          查看版本与分块
        </summary>
        <div className="mt-2 space-y-2">
          {versions.length === 0 ? (
            <p className="text-[12px] text-ink-faint">暂无版本记录</p>
          ) : versions.map((version) => {
            const reindexing = busy === `reindex:${doc.id}:${version.id}`
            const chunks = version.chunks ?? []
            const showAllChunks = expandedVersions[version.id] === true
            const visibleChunks = showAllChunks ? chunks : chunks.slice(0, 2)
            return (
              <div key={version.id} className="rounded-[7px] bg-surface-2 p-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[12px] font-medium text-ink">
                    v{version.version_number} · {GOVERNANCE_STATUS_LABELS[version.status] ?? version.status}
                    <span className="ml-1 font-normal text-ink-faint">· {chunks.length} 个分块 · 引用命中 {version.citation_hits ?? 0}</span>
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="min-h-11 gap-1.5"
                    onClick={() => void onReindex(doc, version)}
                    disabled={!canGovern || busy !== "" || editingChunk !== null}
                    aria-label={`重新索引 v${version.version_number}`}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${reindexing ? "animate-spin" : ""}`} aria-hidden="true" />
                    {reindexing ? "索引中…" : "重新索引"}
                  </Button>
                </div>
                {chunks.length > 0 && (
                  <div className="mt-2 space-y-1 border-t border-[var(--border-soft)] pt-2">
                    {visibleChunks.map((chunk) => {
                      const editing = editingChunk?.id === chunk.id
                      const chunkBusy = busy === `chunk:${doc.id}:${version.id}:${chunk.id}`
                      const pageText = editingChunk?.page.trim() || ""
                      const pageValue = pageText ? Number(pageText) : null
                      const validPage = pageValue === null || (Number.isInteger(pageValue) && pageValue >= 1)
                      return (
                        <div key={chunk.id} className="space-y-1.5 rounded-[6px] border border-transparent py-1">
                          {editing ? (
                            <>
                              <label className="block text-[11px] font-medium text-ink-soft" htmlFor={`knowledge-chunk-text-${chunk.id}`}>分块文本</label>
                              <textarea
                                id={`knowledge-chunk-text-${chunk.id}`}
                                value={editingChunk?.text || ""}
                                onChange={(event) => setEditingChunk((current) => current ? { ...current, text: event.target.value } : current)}
                                rows={4}
                                maxLength={50_000}
                                className="w-full resize-y rounded-[7px] border border-input bg-workspace p-2 text-[13px] leading-relaxed text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                                aria-label={`分块文本 ${chunk.id}`}
                              />
                              <label className="block text-[11px] font-medium text-ink-soft" htmlFor={`knowledge-chunk-page-${chunk.id}`}>页码（可留空）</label>
                              <input
                                id={`knowledge-chunk-page-${chunk.id}`}
                                type="number"
                                min="1"
                                step="1"
                                value={editingChunk?.page || ""}
                                onChange={(event) => setEditingChunk((current) => current ? { ...current, page: event.target.value } : current)}
                                className="min-h-11 w-full rounded-[7px] border border-input bg-workspace px-2.5 text-[13px] text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                                aria-label={`分块页码 ${chunk.id}`}
                              />
                              <div className="flex flex-wrap gap-1.5">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="min-h-11 gap-1.5"
                                  onClick={() => void saveChunk(version, chunk)}
                                  disabled={busy !== "" || !editingChunk?.text.trim() || !validPage}
                                  aria-label={`保存分块 ${chunk.id}`}
                                >
                                  <Save className="h-3.5 w-3.5" aria-hidden="true" />
                                  {chunkBusy ? "保存中…" : "保存分块"}
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="min-h-11 gap-1.5"
                                  onClick={() => setEditingChunk(null)}
                                  disabled={busy !== ""}
                                  aria-label={`取消编辑分块 ${chunk.id}`}
                                >
                                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                                  取消
                                </Button>
                              </div>
                            </>
                          ) : (
                            <div className="flex flex-wrap items-start justify-between gap-1.5">
                              <p className="min-w-0 flex-1 text-[12px] leading-relaxed text-ink-faint">
                                {chunk.page ? `第 ${chunk.page} 页 · ` : ""}{chunk.text || "（空分块）"}
                                {chunk.index_status && <span className="ml-1 text-[11px] text-ink-faint">· {INDEX_STATUS_LABELS[chunk.index_status] ?? chunk.index_status}</span>}
                              </p>
                              {canGovern && (
                                <button
                                  type="button"
                                  className="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-[7px] border border-[var(--border-soft)] px-2.5 text-[12px] text-ink-soft transition-colors hover:bg-[var(--hover)] disabled:opacity-50"
                                  onClick={() => startChunkEdit(chunk)}
                                  disabled={busy !== ""}
                                  aria-label={`编辑分块 ${chunk.id}`}
                                >
                                  <Edit3 className="h-3.5 w-3.5" aria-hidden="true" />
                                  编辑
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                    {chunks.length > 2 && (
                      <button
                        type="button"
                        className="min-h-11 text-[11px] font-medium text-primary"
                        onClick={() => setExpandedVersions((current) => ({ ...current, [version.id]: !showAllChunks }))}
                        aria-expanded={showAllChunks}
                      >
                        {showAllChunks ? "收起分块" : `查看全部 ${chunks.length} 个分块`}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </details>
    </article>
  )
}
