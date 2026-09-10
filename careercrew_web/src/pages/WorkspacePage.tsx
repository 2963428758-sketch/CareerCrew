import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react"
import {
  AlertTriangle,
  Bookmark,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileDiff,
  FileText,
  GitBranch,
  ListTodo,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Wrench,
} from "lucide-react"

import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { networkErrorText } from "@/lib/errors"
import { getAuthSnapshot } from "@/lib/auth"
import {
  createActionItem,
  createBranch,
  createConsultationPlan,
  createConsultationReport,
  createResumeAnnotation,
  createResumeExport,
  createResumeMaterial,
  createResumeMaster,
  createResumeVersion,
  deleteBookmark,
  diffResumeVersions,
  downloadResumeExport,
  listActionItems,
  listBookmarks,
  listBranches,
  listConsultationReports,
  listConsultationPlans,
  listResumeAnnotations,
  listResumeExports,
  listResumeMasters,
  listResumeMaterials,
  listResumeVersions,
  listToolCalls,
  listToolStatus,
  saveBookmark,
  searchWorkspace,
  setToolPolicy,
  updateActionItem,
  updateConsultationPlan,
  updateConsultationReport,
  type ConsultationPlan,
  type ConsultationReport,
  type ResumeAnnotation,
  type ResumeExportJob,
  type ResumeMaster,
  type ResumeMaterial,
  type ResumeVersion,
  type ToolCall,
  type ToolStatus,
  type WorkspaceActionItem,
  type WorkspaceBookmark,
  type WorkspaceBranch,
  type WorkspaceSearchItem,
} from "@/lib/workspace"

type TabKey = "trace" | "consult" | "resume" | "tools"

const TABS: Array<{ key: TabKey; label: string; description: string }> = [
  { key: "trace", label: "追溯与行动", description: "跨会话搜索、书签、分支和行动项" },
  { key: "consult", label: "会诊报告", description: "分歧、证据和人工确认" },
  { key: "resume", label: "简历母版", description: "版本、素材、批注和批量导出" },
  { key: "tools", label: "工具中心", description: "工具状态、权限和调用记录" },
]

const dateText = (value?: string | null) => value ? new Date(value).toLocaleString() : "时间未知"

function StatusPill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "bad" }) {
  return (
    <span className={cn(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px]",
      tone === "ok" && "border-primary/25 bg-primary/10 text-primary",
      tone === "warn" && "border-amber-500/25 bg-amber-500/10 text-amber-700",
      tone === "bad" && "border-destructive/25 bg-destructive/10 text-destructive",
      tone === "neutral" && "border-[var(--border-soft)] bg-surface-2 text-ink-soft",
    )}>
      {children}
    </span>
  )
}

function SectionHeading({ icon, title, description, action }: {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-2.5">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-surface-2 text-ink-soft">
          {icon}
        </div>
        <div className="min-w-0">
          <h2 className="text-[15px] font-[560] text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-[12px] leading-5 text-ink-soft">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  )
}

function PanelEmpty({ children }: { children: ReactNode }) {
  return <div className="rounded-[9px] border border-dashed border-[var(--border-normal)] px-4 py-7 text-center text-[12.5px] text-ink-faint">{children}</div>
}

function LoadingRows({ label = "正在加载…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-[9px] bg-surface-1 px-4 py-5 text-[12.5px] text-ink-faint" aria-live="polite">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  )
}

function ActionItemRow({ item, onUpdate }: {
  item: WorkspaceActionItem
  onUpdate: (id: string, status: WorkspaceActionItem["status"]) => void
}) {
  return (
    <div className="rounded-[8px] border border-[var(--border-soft)] px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className={cn("text-[12.5px]", item.status !== "open" && "text-ink-faint line-through")}>{item.title}</span>
        <StatusPill tone={item.status === "open" ? "warn" : "ok"}>
          {item.status === "open" ? "待处理" : item.status === "done" ? "已完成" : "已忽略"}
        </StatusPill>
      </div>
      <p className="mt-1 line-clamp-2 text-[11px] text-ink-faint">来源：{item.source_snippet}</p>
      {item.status === "open" && (
        <Button variant="ghost" size="sm" className="mt-1 min-h-10 px-1.5 text-[11px]" onClick={() => onUpdate(item.id, "done")}>
          <span className="inline-flex items-center"><CheckCircle2 className="mr-1 h-3.5 w-3.5" /><span>标记完成</span></span>
        </Button>
      )}
    </div>
  )
}

function SearchResultRow({
  item, bookmarked, busyKey, actionMessageId, actionTitle, setActionTitle, setActionMessageId,
  onToggleBookmark, onActionSubmit, onBranch, onMakeReport,
}: {
  item: WorkspaceSearchItem
  bookmarked: boolean
  busyKey: string | null
  actionMessageId: string | null
  actionTitle: string
  setActionTitle: (value: string) => void
  setActionMessageId: (value: string | null) => void
  onToggleBookmark: (item: WorkspaceSearchItem) => void
  onActionSubmit: (event: FormEvent, messageId: string) => void
  onBranch: (item: WorkspaceSearchItem) => void
  onMakeReport: (item: WorkspaceSearchItem) => void
}) {
  return (
    <div className="rounded-[9px] border border-[var(--border-soft)] bg-surface-1 p-3 transition-colors duration-100 hover:border-[var(--border-normal)]">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-faint">
        <span>{item.thread_title || "未命名会话"}</span><span>·</span><span>{item.role === "assistant" ? "助手回答" : "我的消息"}</span><span>·</span><span>{dateText(item.created_at)}</span>
      </div>
      <p className="mt-2 text-[13px] leading-6 text-ink">{item.snippet}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Button variant="ghost" size="sm" className="min-h-11 gap-1.5" aria-label={bookmarked ? "取消收藏这条消息" : "收藏这条消息"} disabled={busyKey === "bookmark:" + item.message_id} onClick={() => onToggleBookmark(item)}>
          <span className="inline-flex items-center gap-1.5">{bookmarked ? <Check className="h-3.5 w-3.5 text-primary" strokeWidth={1.8} /> : <Bookmark className="h-3.5 w-3.5" strokeWidth={1.7} />}<span>{bookmarked ? "已收藏" : "收藏"}</span></span>
        </Button>
        <Button variant="ghost" size="sm" className="min-h-11 gap-1.5" onClick={() => setActionMessageId(actionMessageId === item.message_id ? null : item.message_id)}><span className="inline-flex items-center gap-1.5"><ListTodo className="h-3.5 w-3.5" strokeWidth={1.7} /><span>创建行动项</span></span></Button>
        <Button variant="ghost" size="sm" className="min-h-11 gap-1.5" disabled={busyKey === "branch:" + item.message_id} onClick={() => onBranch(item)}><span className="inline-flex items-center gap-1.5"><GitBranch className="h-3.5 w-3.5" strokeWidth={1.7} /><span>创建分支</span></span></Button>
        {item.role === "assistant" && <Button variant="ghost" size="sm" className="min-h-11 gap-1.5" disabled={busyKey === "report:" + item.message_id} onClick={() => onMakeReport(item)}><span className="inline-flex items-center gap-1.5"><ClipboardCheck className="h-3.5 w-3.5" strokeWidth={1.7} /><span>生成会诊报告</span></span></Button>}
      </div>
      {actionMessageId === item.message_id && (
        <form onSubmit={(event) => onActionSubmit(event, item.message_id)} className="mt-2 flex flex-col gap-2 border-t border-[var(--border-soft)] pt-2 sm:flex-row">
          <label htmlFor="action-title" className="sr-only">行动项标题</label>
          <Input id="action-title" autoFocus value={actionTitle} onChange={(event) => setActionTitle(event.target.value)} placeholder="例如：补充项目指标" className="min-h-11 flex-1" />
          <Button type="submit" className="min-h-11" disabled={!actionTitle.trim() || busyKey === "action:" + item.message_id}>保存行动项</Button>
        </form>
      )}
    </div>
  )
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function WorkspacePage() {
  const isAdmin = getAuthSnapshot().user?.role === "admin"
  const [tab, setTab] = useState<TabKey>("trace")
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const [query, setQuery] = useState("")
  const [searchItems, setSearchItems] = useState<WorkspaceSearchItem[]>([])
  const [searchMode, setSearchMode] = useState<string | null>(null)
  const [bookmarks, setBookmarks] = useState<WorkspaceBookmark[]>([])
  const [actionItems, setActionItems] = useState<WorkspaceActionItem[]>([])
  const [branches, setBranches] = useState<WorkspaceBranch[]>([])
  const [actionMessageId, setActionMessageId] = useState<string | null>(null)
  const [actionTitle, setActionTitle] = useState("")

  const [reports, setReports] = useState<ConsultationReport[]>([])
  const [plans, setPlans] = useState<Record<string, ConsultationPlan[]>>({})

  const [masters, setMasters] = useState<ResumeMaster[]>([])
  const [selectedMasterId, setSelectedMasterId] = useState<string | null>(null)
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [materials, setMaterials] = useState<ResumeMaterial[]>([])
  const [annotations, setAnnotations] = useState<ResumeAnnotation[]>([])
  const [exports, setExports] = useState<ResumeExportJob[]>([])
  const [masterTitle, setMasterTitle] = useState("")
  const [masterContent, setMasterContent] = useState("")
  const [versionLabel, setVersionLabel] = useState("")
  const [versionContent, setVersionContent] = useState("")
  const [materialTitle, setMaterialTitle] = useState("")
  const [materialResult, setMaterialResult] = useState("")
  const [annotationStart, setAnnotationStart] = useState("0")
  const [annotationEnd, setAnnotationEnd] = useState("0")
  const [annotationNote, setAnnotationNote] = useState("")
  const [leftVersionId, setLeftVersionId] = useState("")
  const [rightVersionId, setRightVersionId] = useState("")
  const [diff, setDiff] = useState<{ left_label: string; right_label: string; changed: boolean; unified_diff: string } | null>(null)
  const [exportSelection, setExportSelection] = useState<string[]>([])

  const [tools, setTools] = useState<ToolStatus[]>([])
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])

  const run = async (key: string, action: () => Promise<void>) => {
    if (busyKey) return
    setBusyKey(key)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(networkErrorText(err, "操作失败，请稍后重试"))
    } finally {
      setBusyKey(null)
    }
  }

  useEffect(() => {
    let disposed = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        if (tab === "trace") {
          const [bookmarkRows, actionRows, branchRows] = await Promise.all([
            listBookmarks(), listActionItems(), listBranches(),
          ])
          if (!disposed) {
            setBookmarks(bookmarkRows)
            setActionItems(actionRows)
            setBranches(branchRows)
          }
        } else if (tab === "consult") {
          const rows = await listConsultationReports()
          const planRows = await Promise.all(rows.map(async (report) => [report.id, await listConsultationPlans(report.id)] as const))
          if (!disposed) {
            setReports(rows)
            setPlans(Object.fromEntries(planRows))
          }
        } else if (tab === "resume") {
          const [masterRows, materialRows, exportRows] = await Promise.all([
            listResumeMasters(), listResumeMaterials(), listResumeExports(),
          ])
          if (!disposed) {
            setMasters(masterRows)
            setMaterials(materialRows)
            setExports(exportRows)
            setSelectedMasterId((current) => current && masterRows.some((row) => row.id === current) ? current : masterRows[0]?.id ?? null)
          }
        } else {
          const [toolResponse, callRows] = await Promise.all([listToolStatus("chat"), listToolCalls()])
          if (!disposed) {
            setTools(toolResponse.tools)
            setToolCalls(callRows)
          }
        }
      } catch (err) {
        if (!disposed) setError(networkErrorText(err, "工作台数据加载失败"))
      } finally {
        if (!disposed) setLoading(false)
      }
    }
    void load()
    return () => { disposed = true }
  }, [tab, refreshKey])

  useEffect(() => {
    if (tab !== "resume" || !selectedMasterId) {
      setVersions([])
      setAnnotations([])
      return
    }
    let disposed = false
    void listResumeVersions(selectedMasterId)
      .then(async (rows) => {
        if (disposed) return
        setVersions(rows)
        setLeftVersionId(rows[1]?.id ?? rows[0]?.id ?? "")
        setRightVersionId(rows[0]?.id ?? "")
        setExportSelection([])
      })
      .catch((err) => { if (!disposed) setError(networkErrorText(err, "简历版本加载失败")) })
    return () => { disposed = true }
  }, [tab, selectedMasterId, refreshKey])

  useEffect(() => {
    if (tab !== "resume" || !rightVersionId) return
    let disposed = false
    void listResumeAnnotations(rightVersionId)
      .then((rows) => { if (!disposed) setAnnotations(rows) })
      .catch((err) => { if (!disposed) setError(networkErrorText(err, "简历批注加载失败")) })
    return () => { disposed = true }
  }, [tab, rightVersionId])

  const hasPendingExports = tab === "resume" && exports.some((job) => job.status === "queued" || job.status === "running")
  useEffect(() => {
    if (!hasPendingExports) return
    let disposed = false
    let attempts = 0
    let timer: number | undefined
    const poll = async () => {
      if (disposed || attempts >= 30) return
      attempts += 1
      try {
        const rows = await listResumeExports()
        if (!disposed) setExports(rows)
      } catch (err) {
        if (!disposed) setError(networkErrorText(err, "导出任务状态加载失败"))
      }
      if (!disposed && attempts < 30) timer = window.setTimeout(() => { void poll() }, 2000)
    }
    timer = window.setTimeout(() => { void poll() }, 2000)
    return () => {
      disposed = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [hasPendingExports])

  const bookmarkIds = useMemo(() => new Set(bookmarks.map((item) => item.message_id)), [bookmarks])
  const selectedVersion = versions.find((version) => version.id === rightVersionId)

  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    const text = query.trim()
    if (!text) {
      setError("请输入要搜索的关键词")
      return
    }
    void run("search", async () => {
      const response = await searchWorkspace(text)
      setSearchItems(response.items)
      setSearchMode(response.mode)
    })
  }

  const toggleBookmark = (item: WorkspaceSearchItem) => {
    void run(`bookmark:${item.message_id}`, async () => {
      if (bookmarkIds.has(item.message_id)) {
        await deleteBookmark(item.message_id)
        setBookmarks((current) => current.filter((bookmark) => bookmark.message_id !== item.message_id))
      } else {
        const bookmark = await saveBookmark(item.message_id)
        setBookmarks((current) => [bookmark, ...current.filter((row) => row.message_id !== item.message_id)])
      }
    })
  }

  const submitActionItem = (event: FormEvent, messageId: string) => {
    event.preventDefault()
    const title = actionTitle.trim()
    if (!title) return
    void run(`action:${messageId}`, async () => {
      const item = await createActionItem(messageId, title)
      setActionItems((current) => [item, ...current])
      setActionMessageId(null)
      setActionTitle("")
    })
  }

  const handleBranch = (item: WorkspaceSearchItem) => {
    void run(`branch:${item.message_id}`, async () => {
      const branch = await createBranch(item.thread_id, item.message_id)
      setBranches((current) => [branch, ...current])
    })
  }

  const makeReport = (item: WorkspaceSearchItem) => {
    void run(`report:${item.message_id}`, async () => {
      const report = await createConsultationReport(item.message_id)
      setReports((current) => [report, ...current.filter((row) => row.id !== report.id)])
      setTab("consult")
    })
  }

  const confirmReport = (report: ConsultationReport) => {
    void run(`report-status:${report.id}`, async () => {
      const next = await updateConsultationReport(report.id, report.status === "confirmed" ? "draft" : "confirmed", report.version)
      setReports((current) => current.map((row) => row.id === next.id ? next : row))
    })
  }

  const makePlan = (report: ConsultationReport) => {
    void run(`plan:${report.id}`, async () => {
      const steps = [
        { title: "核验会诊证据与时效", note: "检查引用、事实和适用条件" },
        { title: "选择方案并记录执行边界", note: "将确认后的方案拆成可追踪行动" },
      ]
      const plan = await createConsultationPlan(report.id, "会诊执行计划草案", steps)
      setPlans((current) => ({ ...current, [report.id]: [plan, ...(current[report.id] ?? [])] }))
    })
  }

  const confirmPlan = (plan: ConsultationPlan) => {
    void run("plan-status:" + plan.id, async () => {
      const next = await updateConsultationPlan(
        plan.id,
        plan.status === "confirmed" ? "draft" : "confirmed",
        plan.version,
      )
      setPlans((current) => Object.fromEntries(
        Object.entries(current).map(([reportId, rows]) => [
          reportId,
          rows.map((row) => row.id === next.id ? next : row),
        ]),
      ))
    })
  }

  const createMaster = (event: FormEvent) => {
    event.preventDefault()
    if (!masterTitle.trim() || !masterContent.trim()) return
    void run("master", async () => {
      const master = await createResumeMaster(masterTitle.trim(), masterContent)
      setMasters((current) => [master, ...current])
      setSelectedMasterId(master.id)
      setMasterTitle("")
      setMasterContent("")
    })
  }

  const createVersion = (event: FormEvent) => {
    event.preventDefault()
    if (!selectedMasterId || !versionLabel.trim() || !versionContent.trim()) return
    void run("version", async () => {
      const version = await createResumeVersion(selectedMasterId, versionLabel.trim(), versionContent, rightVersionId || undefined)
      setVersions((current) => [version, ...current])
      setRightVersionId(version.id)
      setVersionLabel("")
      setVersionContent("")
    })
  }

  const createMaterial = (event: FormEvent) => {
    event.preventDefault()
    if (!materialTitle.trim() || !materialResult.trim()) return
    void run("material", async () => {
      const material = await createResumeMaterial(materialTitle.trim(), materialResult.trim())
      setMaterials((current) => [material, ...current])
      setMaterialTitle("")
      setMaterialResult("")
    })
  }

  const createAnnotation = (event: FormEvent) => {
    event.preventDefault()
    if (!selectedVersion || !annotationNote.trim()) return
    void run("annotation", async () => {
      const annotation = await createResumeAnnotation(
        selectedVersion.id,
        Number(annotationStart),
        Number(annotationEnd),
        annotationNote.trim(),
      )
      setAnnotations((current) => [annotation, ...current])
      setAnnotationNote("")
    })
  }

  const loadDiff = () => {
    if (!leftVersionId || !rightVersionId || leftVersionId === rightVersionId) return
    void run("diff", async () => setDiff(await diffResumeVersions(leftVersionId, rightVersionId)))
  }

  const toggleExportVersion = (id: string) => {
    setExportSelection((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  }

  const startExport = () => {
    if (exportSelection.length === 0) return
    void run("export", async () => {
      const job = await createResumeExport(exportSelection)
      setExports((current) => [job, ...current])
    })
  }

  const downloadExport = (job: ResumeExportJob) => {
    void run(`download:${job.id}`, async () => {
      const response = await downloadResumeExport(job.id)
      if (!response.ok) throw new Error("导出文件尚未完成")
      saveBlob(await response.blob(), `careercrew-resume-${job.id.slice(0, 8)}.zip`)
    })
  }

  const toggleTool = (tool: ToolStatus) => {
    void run(`tool:${tool.id}`, async () => {
      const updated = await setToolPolicy(tool.id, !tool.enabled)
      setTools((current) => current.map((row) => row.id === updated.id ? updated : row))
    })
  }

  return (
    <div className="flex h-full flex-col">
      <WorkspaceHeader
        parent="CareerCrew"
        title="工作台"
        subtitle="跨会话可追溯 · 人工确认后执行"
        actions={(
          <Button
            variant="ghost"
            size="icon"
            className="min-h-11 min-w-11"
            aria-label="刷新工作台"
            onClick={() => setRefreshKey((value) => value + 1)}
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} strokeWidth={1.7} />
          </Button>
        )}
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8">
        <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <Card className="bg-surface-1">
              <CardContent className="flex items-center gap-3 p-4">
                <Search className="h-4 w-4 text-primary" strokeWidth={1.7} />
                <div><div className="text-[11px] text-ink-faint">已收藏消息</div><div className="text-[18px] font-medium text-ink">{bookmarks.length}</div></div>
              </CardContent>
            </Card>
            <Card className="bg-surface-1">
              <CardContent className="flex items-center gap-3 p-4">
                <ClipboardCheck className="h-4 w-4 text-amber-600" strokeWidth={1.7} />
                <div><div className="text-[11px] text-ink-faint">待办行动项</div><div className="text-[18px] font-medium text-ink">{actionItems.filter((item) => item.status === "open").length}</div></div>
              </CardContent>
            </Card>
            <Card className="bg-surface-1">
              <CardContent className="flex items-center gap-3 p-4">
                <ShieldCheck className="h-4 w-4 text-agent-salary" strokeWidth={1.7} />
                <div><div className="text-[11px] text-ink-faint">已确认会诊</div><div className="text-[18px] font-medium text-ink">{reports.filter((report) => report.status === "confirmed").length}</div></div>
              </CardContent>
            </Card>
          </div>

          <div role="tablist" aria-label="工作台模块" className="flex gap-1 overflow-x-auto border-b border-[var(--border-soft)]">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                aria-controls={`workspace-panel-${item.key}`}
                onClick={() => setTab(item.key)}
                className={cn(
                  "min-h-11 shrink-0 border-b-2 px-3 text-left text-[12.5px] transition-colors duration-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
                  tab === item.key ? "border-primary font-medium text-ink" : "border-transparent text-ink-soft hover:border-[var(--border-normal)] hover:text-ink",
                )}
              >
                <span className="block">{item.label}</span>
                <span className="hidden text-[10.5px] text-ink-faint sm:block">{item.description}</span>
              </button>
            ))}
          </div>

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-[9px] border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-[12.5px] text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.7} />
              <span>{error}</span>
            </div>
          )}

          {loading ? <LoadingRows /> : (
            <div id={`workspace-panel-${tab}`} role="tabpanel" aria-label={TABS.find((item) => item.key === tab)?.label}>
              {tab === "trace" && (
                <TracePanel
                  query={query}
                  setQuery={setQuery}
                  searchMode={searchMode}
                  searchItems={searchItems}
                  bookmarks={bookmarks}
                  actionItems={actionItems}
                  branches={branches}
                  actionMessageId={actionMessageId}
                  actionTitle={actionTitle}
                  setActionTitle={setActionTitle}
                  setActionMessageId={setActionMessageId}
                  busyKey={busyKey}
                  onSearch={submitSearch}
                  onToggleBookmark={toggleBookmark}
                  onActionSubmit={submitActionItem}
                  onBranch={handleBranch}
                  onMakeReport={makeReport}
                  onActionUpdate={(id, status) => void run(`action-status:${id}`, async () => {
                    const updated = await updateActionItem(id, status)
                    setActionItems((current) => current.map((item) => item.id === updated.id ? updated : item))
                  })}
                />
              )}
              {tab === "consult" && <ConsultPanel reports={reports} plans={plans} busyKey={busyKey} onConfirm={confirmReport} onMakePlan={makePlan} onUpdatePlan={confirmPlan} />}
              {tab === "resume" && (
                <ResumePanel
                  masters={masters}
                  selectedMasterId={selectedMasterId}
                  onSelectMaster={setSelectedMasterId}
                  versions={versions}
                  materials={materials}
                  annotations={annotations}
                  exports={exports}
                  leftVersionId={leftVersionId}
                  rightVersionId={rightVersionId}
                  diff={diff}
                  exportSelection={exportSelection}
                  masterTitle={masterTitle}
                  masterContent={masterContent}
                  versionLabel={versionLabel}
                  versionContent={versionContent}
                  materialTitle={materialTitle}
                  materialResult={materialResult}
                  annotationStart={annotationStart}
                  annotationEnd={annotationEnd}
                  annotationNote={annotationNote}
                  setMasterTitle={setMasterTitle}
                  setMasterContent={setMasterContent}
                  setVersionLabel={setVersionLabel}
                  setVersionContent={setVersionContent}
                  setMaterialTitle={setMaterialTitle}
                  setMaterialResult={setMaterialResult}
                  setAnnotationStart={setAnnotationStart}
                  setAnnotationEnd={setAnnotationEnd}
                  setAnnotationNote={setAnnotationNote}
                  setLeftVersionId={setLeftVersionId}
                  setRightVersionId={setRightVersionId}
                  onCreateMaster={createMaster}
                  onCreateVersion={createVersion}
                  onCreateMaterial={createMaterial}
                  onCreateAnnotation={createAnnotation}
                  onDiff={loadDiff}
                  onToggleExportVersion={toggleExportVersion}
                  onExport={startExport}
                  onDownload={downloadExport}
                  busyKey={busyKey}
                />
              )}
              {tab === "tools" && <ToolsPanel tools={tools} calls={toolCalls} busyKey={busyKey} isAdmin={isAdmin} onToggle={toggleTool} />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TracePanel({
  query, setQuery, searchMode, searchItems, bookmarks, actionItems, branches,
  actionMessageId, actionTitle, setActionTitle, setActionMessageId, busyKey,
  onSearch, onToggleBookmark, onActionSubmit, onBranch, onMakeReport, onActionUpdate,
}: {
  query: string
  setQuery: (value: string) => void
  searchMode: string | null
  searchItems: WorkspaceSearchItem[]
  bookmarks: WorkspaceBookmark[]
  actionItems: WorkspaceActionItem[]
  branches: WorkspaceBranch[]
  actionMessageId: string | null
  actionTitle: string
  setActionTitle: (value: string) => void
  setActionMessageId: (value: string | null) => void
  busyKey: string | null
  onSearch: (event: FormEvent) => void
  onToggleBookmark: (item: WorkspaceSearchItem) => void
  onActionSubmit: (event: FormEvent, messageId: string) => void
  onBranch: (item: WorkspaceSearchItem) => void
  onMakeReport: (item: WorkspaceSearchItem) => void
  onActionUpdate: (id: string, status: WorkspaceActionItem["status"]) => void
}) {
  const hasRelatedLinks = bookmarks.length > 0 || branches.length > 0
  return (
    <div className="flex flex-col gap-4">
      <SectionHeading icon={<Search className="h-4 w-4" strokeWidth={1.7} />} title="跨会话搜索" description="先用全文回退快速定位，再从原消息继续收藏、分支或转成行动项。" />
      <form onSubmit={onSearch} className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="workspace-search" className="sr-only">跨会话搜索</label>
        <Input id="workspace-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目、岗位、面试复盘或任意关键词" className="min-h-11 flex-1" />
        <Button type="submit" className="min-h-11 gap-2 sm:min-w-[92px]"><span className="inline-flex items-center gap-2"><Search className="h-4 w-4" strokeWidth={1.7} /><span>搜索</span></span></Button>
      </form>
      {searchMode && <p className="text-[11px] text-ink-faint">当前检索模式：{searchMode === "text_fallback" ? "全文回退" : searchMode}。结果只来自当前账号可访问的会话。</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(260px,0.75fr)]">
        <Card>
          <CardHeader className="pb-2"><CardTitle>搜索结果</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex flex-col gap-2">
            {searchItems.length === 0 ? <PanelEmpty>输入关键词开始查找；无结果时可以换一个项目名或技能词。</PanelEmpty> : searchItems.map((item) => (
              <SearchResultRow
                key={item.message_id}
                item={item}
                bookmarked={bookmarks.some((row) => row.message_id === item.message_id)}
                busyKey={busyKey}
                actionMessageId={actionMessageId}
                actionTitle={actionTitle}
                setActionTitle={setActionTitle}
                setActionMessageId={setActionMessageId}
                onToggleBookmark={onToggleBookmark}
                onActionSubmit={onActionSubmit}
                onBranch={onBranch}
                onMakeReport={onMakeReport}
              />
            ))}
            </div>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="pb-2"><CardTitle>行动项</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-2">
              <div className="flex flex-col gap-2">
              {actionItems.length === 0 ? <PanelEmpty>从搜索结果把一个回答转成下一步行动。</PanelEmpty> : actionItems.map((item) => (
                <ActionItemRow key={item.id} item={item} onUpdate={onActionUpdate} />
              ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2"><CardTitle>书签与分支</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-2">
              <div className="flex flex-col gap-2">
                {!hasRelatedLinks ? <PanelEmpty>重要结论可以先收藏，另一条路径可以从原消息创建分支。</PanelEmpty> : (
                  <>
                    {bookmarks.slice(0, 3).map((bookmark) => (
                      <div key={"bookmark-" + bookmark.id} className="flex items-start gap-2 text-[12px] text-ink-soft"><Bookmark className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" /><span className="line-clamp-2">{bookmark.snippet}</span></div>
                    ))}
                    {branches.slice(0, 3).map((branch) => (
                      <div key={"branch-" + branch.id} className="flex items-start gap-2 text-[12px] text-ink-soft"><GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-agent-salary" /><span className="line-clamp-2">{branch.title} · 已复制 {branch.message_count} 条消息</span></div>
                    ))}
                  </>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function ConsultPanel({ reports, plans, busyKey, onConfirm, onMakePlan, onUpdatePlan }: {
  reports: ConsultationReport[]
  plans: Record<string, ConsultationPlan[]>
  busyKey: string | null
  onConfirm: (report: ConsultationReport) => void
  onMakePlan: (report: ConsultationReport) => void
  onUpdatePlan: (plan: ConsultationPlan) => void
}) {
  return (
    <div className="flex flex-col gap-4">
      <SectionHeading icon={<ClipboardCheck className="h-4 w-4" strokeWidth={1.7} />} title="可解释会诊报告" description="把已完成的会诊回答整理成共识、分歧、证据和风险；确认前仍是草案。" />
      {reports.length === 0 ? <PanelEmpty>还没有会诊报告。可以在追溯搜索中对助手回答生成报告。</PanelEmpty> : reports.map((report) => (
        <Card key={report.id}>
          <CardHeader className="flex-row items-start justify-between gap-3 pb-2">
            <div><CardTitle>会诊报告</CardTitle><p className="mt-1 text-[11px] text-ink-faint">来源消息 {report.source_message_id.slice(0, 12)} · {dateText(report.generated_at)}</p></div>
            <StatusPill tone={report.status === "confirmed" ? "ok" : "warn"}>{report.status === "confirmed" ? "已确认" : "草案"}</StatusPill>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="rounded-[8px] bg-surface-1 px-3 py-2.5 text-[12.5px] leading-5 text-ink">{report.source_answer}</p>
            <div className="grid gap-3 lg:grid-cols-3">
              <ReportList title="共识" empty="暂无共识" items={report.consensus.map((item) => `${item.point}（${item.supporters.join("、")}）`)} tone="ok" />
              <ReportList title="分歧" empty="暂无明显分歧" items={report.disagreements.map((item) => item.summary)} tone="warn" />
              <ReportList title="风险" empty="暂无额外风险" items={report.risks.map((item) => item.summary)} tone="bad" />
            </div>
            <div className="flex flex-wrap gap-2 border-t border-[var(--border-soft)] pt-3">
              <Button variant={report.status === "confirmed" ? "outline" : "default"} className="min-h-11 gap-1.5" disabled={busyKey === `report-status:${report.id}`} onClick={() => onConfirm(report)}>
                <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.7} />{report.status === "confirmed" ? "撤回确认" : "确认报告"}
              </Button>
              <Button variant="outline" className="min-h-11 gap-1.5" disabled={busyKey === `plan:${report.id}`} onClick={() => onMakePlan(report)}><ListTodo className="h-3.5 w-3.5" strokeWidth={1.7} />生成执行计划草案</Button>
            </div>
            {(plans[report.id] ?? []).map((plan) => (
              <div key={plan.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] border border-primary/20 bg-primary/5 px-3 py-2 text-[12px] text-ink">
                <div><span className="font-medium">{plan.title}</span><span className="ml-2 text-ink-soft">{plan.steps.length} 个步骤 · {plan.status === "draft" ? "待确认" : "已确认"}</span></div>
                <Button variant="ghost" size="sm" className="min-h-10" disabled={busyKey === `plan-status:${plan.id}`} onClick={() => onUpdatePlan(plan)}>{plan.status === "draft" ? "确认计划" : "撤回确认"}</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function ReportList({ title, items, empty, tone }: { title: string; items: string[]; empty: string; tone: "ok" | "warn" | "bad" }) {
  return <div className="rounded-[8px] border border-[var(--border-soft)] p-3"><div className="mb-2 flex items-center justify-between gap-2"><span className="text-[12px] font-medium text-ink">{title}</span><StatusPill tone={tone}>{items.length}</StatusPill></div>{items.length === 0 ? <p className="text-[11.5px] text-ink-faint">{empty}</p> : <ul className="flex flex-col gap-1.5 text-[12px] leading-5 text-ink-soft">{items.slice(0, 5).map((item, index) => <li key={`${item}-${index}`} className="flex gap-1.5"><span className="text-ink-faint">·</span><span>{item}</span></li>)}</ul>}</div>
}

function ResumePanel({
  masters, selectedMasterId, onSelectMaster, versions, materials, annotations, exports, leftVersionId, rightVersionId,
  diff, exportSelection, masterTitle, masterContent, versionLabel, versionContent, materialTitle, materialResult,
  annotationStart, annotationEnd, annotationNote, setMasterTitle, setMasterContent, setVersionLabel, setVersionContent,
  setMaterialTitle, setMaterialResult, setAnnotationStart, setAnnotationEnd, setAnnotationNote, setLeftVersionId,
  setRightVersionId, onCreateMaster, onCreateVersion, onCreateMaterial, onCreateAnnotation, onDiff, onToggleExportVersion,
  onExport, onDownload, busyKey,
}: {
  masters: ResumeMaster[]; selectedMasterId: string | null; onSelectMaster: (id: string) => void; versions: ResumeVersion[]
  materials: ResumeMaterial[]; annotations: ResumeAnnotation[]; exports: ResumeExportJob[]; leftVersionId: string; rightVersionId: string
  diff: { left_label: string; right_label: string; changed: boolean; unified_diff: string } | null; exportSelection: string[]
  masterTitle: string; masterContent: string; versionLabel: string; versionContent: string; materialTitle: string; materialResult: string
  annotationStart: string; annotationEnd: string; annotationNote: string; setMasterTitle: (value: string) => void; setMasterContent: (value: string) => void
  setVersionLabel: (value: string) => void; setVersionContent: (value: string) => void; setMaterialTitle: (value: string) => void; setMaterialResult: (value: string) => void
  setAnnotationStart: (value: string) => void; setAnnotationEnd: (value: string) => void; setAnnotationNote: (value: string) => void; setLeftVersionId: (value: string) => void
  setRightVersionId: (value: string) => void; onCreateMaster: (event: FormEvent) => void; onCreateVersion: (event: FormEvent) => void
  onCreateMaterial: (event: FormEvent) => void; onCreateAnnotation: (event: FormEvent) => void; onDiff: () => void; onToggleExportVersion: (id: string) => void
  onExport: () => void; onDownload: (job: ResumeExportJob) => void; busyKey: string | null
}) {
  return (
    <div className="flex flex-col gap-4">
      <SectionHeading icon={<FileText className="h-4 w-4" strokeWidth={1.7} />} title="通用简历母版" description="母版保留完整经历，岗位稿从版本关系派生；导出前仍可查看差异和批注。" />
      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card>
          <CardHeader className="pb-2"><CardTitle>母版列表</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {masters.length === 0 ? <PanelEmpty>还没有母版，在下方创建第一份通用简历。</PanelEmpty> : masters.map((master) => <button key={master.id} type="button" onClick={() => onSelectMaster(master.id)} className={cn("rounded-[8px] border px-3 py-2 text-left transition-colors duration-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40", selectedMasterId === master.id ? "border-primary/40 bg-primary/5" : "border-[var(--border-soft)] hover:border-[var(--border-normal)]")}><span className="block truncate text-[12.5px] font-medium text-ink">{master.title}</span><span className="mt-1 block text-[10.5px] text-ink-faint">更新于 {dateText(master.updated_at)}</span></button>)}
            <form onSubmit={onCreateMaster} className="mt-2 flex flex-col gap-2 border-t border-[var(--border-soft)] pt-3"><label htmlFor="master-title" className="text-[11px] text-ink-faint">新母版名称</label><Input id="master-title" value={masterTitle} onChange={(event) => setMasterTitle(event.target.value)} placeholder="例如：后端工程师母版" className="min-h-11" /><label htmlFor="master-content" className="text-[11px] text-ink-faint">简历正文</label><Textarea id="master-content" value={masterContent} onChange={(event) => setMasterContent(event.target.value)} placeholder="粘贴完整简历内容" /><Button type="submit" className="min-h-11 gap-1.5" disabled={!masterTitle.trim() || !masterContent.trim() || busyKey === "master"}><Plus className="h-3.5 w-3.5" />创建母版</Button></form>
          </CardContent>
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          {!selectedMasterId ? <PanelEmpty>选择或创建一个母版后管理版本。</PanelEmpty> : <>
            <Card>
              <CardHeader className="flex-row items-center justify-between gap-3 pb-2"><CardTitle>版本与差异</CardTitle><StatusPill>{versions.length} 个版本</StatusPill></CardHeader>
              <CardContent className="flex flex-col gap-3">
                {versions.length === 0 ? <PanelEmpty>该母版还没有版本。</PanelEmpty> : <>
                  <div className="flex flex-col gap-2"><div className="flex flex-wrap items-center gap-2"><label htmlFor="left-version" className="text-[11px] text-ink-faint">左侧</label><select id="left-version" value={leftVersionId} onChange={(event) => setLeftVersionId(event.target.value)} className="min-h-11 min-w-[150px] rounded-[7px] border border-input bg-card px-2 text-[12px] text-ink">{versions.map((version) => <option key={version.id} value={version.id}>{version.label}</option>)}</select><label htmlFor="right-version" className="text-[11px] text-ink-faint">右侧</label><select id="right-version" value={rightVersionId} onChange={(event) => setRightVersionId(event.target.value)} className="min-h-11 min-w-[150px] rounded-[7px] border border-input bg-card px-2 text-[12px] text-ink">{versions.map((version) => <option key={version.id} value={version.id}>{version.label}</option>)}</select><Button variant="outline" className="min-h-11 gap-1.5" disabled={!leftVersionId || !rightVersionId || leftVersionId === rightVersionId || busyKey === "diff"} onClick={onDiff}><FileDiff className="h-3.5 w-3.5" />查看差异</Button></div>{diff && <pre className="max-h-[240px] overflow-auto rounded-[8px] bg-surface-1 p-3 text-[11px] leading-5 text-ink-soft">{diff.changed ? diff.unified_diff || "内容有变化，但没有生成文本差异。" : "两个版本内容相同。"}</pre>}</div>
                  <div className="grid gap-2 sm:grid-cols-2">{versions.map((version) => <label key={version.id} className="flex cursor-pointer items-start gap-2 rounded-[8px] border border-[var(--border-soft)] p-2.5 hover:border-[var(--border-normal)]"><input type="checkbox" checked={exportSelection.includes(version.id)} onChange={() => onToggleExportVersion(version.id)} className="mt-1 h-4 w-4 accent-primary" /><span className="min-w-0"><span className="block truncate text-[12.5px] text-ink">{version.label}</span><span className="block text-[10.5px] text-ink-faint">v{version.version_number} · {version.kind === "master" ? "母版" : "派生"}</span></span></label>)}</div>
                  <div className="flex flex-wrap items-center gap-2"><Button className="min-h-11 gap-1.5" disabled={exportSelection.length === 0 || busyKey === "export"} onClick={onExport}><Download className="h-3.5 w-3.5" />批量导出 PDF/DOCX（{exportSelection.length}）</Button><span className="text-[11px] text-ink-faint">最多 20 个版本，文件保留 1 小时</span></div>
                </>}
                <form onSubmit={onCreateVersion} className="flex flex-col gap-2 border-t border-[var(--border-soft)] pt-3"><div className="grid gap-2 sm:grid-cols-[180px_minmax(0,1fr)]"><Input aria-label="版本名称" value={versionLabel} onChange={(event) => setVersionLabel(event.target.value)} placeholder="岗位定制版" className="min-h-11" /><Textarea aria-label="版本内容" value={versionContent} onChange={(event) => setVersionContent(event.target.value)} placeholder="输入派生版本正文" /></div><Button type="submit" variant="outline" className="min-h-11 self-start" disabled={!versionLabel.trim() || !versionContent.trim() || busyKey === "version"}>保存派生版本</Button></form>
              </CardContent>
            </Card>

            <div className="grid gap-4 xl:grid-cols-2">
              <Card><CardHeader className="pb-2"><CardTitle>批注</CardTitle></CardHeader><CardContent className="flex flex-col gap-2"><form onSubmit={onCreateAnnotation} className="grid gap-2 sm:grid-cols-2"><Input aria-label="批注起点" type="number" min="0" value={annotationStart} onChange={(event) => setAnnotationStart(event.target.value)} placeholder="起点" /><Input aria-label="批注终点" type="number" min="0" value={annotationEnd} onChange={(event) => setAnnotationEnd(event.target.value)} placeholder="终点" /><Input aria-label="批注内容" value={annotationNote} onChange={(event) => setAnnotationNote(event.target.value)} placeholder="对选中文本的说明" className="sm:col-span-2 min-h-11" /><Button type="submit" variant="outline" className="min-h-11 sm:col-span-2" disabled={!annotationNote.trim() || busyKey === "annotation"}>添加批注</Button></form>{annotations.length === 0 ? <p className="text-[11.5px] text-ink-faint">选择当前版本的字符范围，记录需要修改或核验的地方。</p> : annotations.map((annotation) => <div key={annotation.id} className="rounded-[8px] bg-surface-1 px-3 py-2 text-[11.5px] text-ink-soft">字符 {annotation.start_offset}–{annotation.end_offset}：{annotation.note}</div>)}</CardContent></Card>
              <Card><CardHeader className="pb-2"><CardTitle>经历素材复用</CardTitle></CardHeader><CardContent className="flex flex-col gap-2"><form onSubmit={onCreateMaterial} className="flex flex-col gap-2"><Input aria-label="素材标题" value={materialTitle} onChange={(event) => setMaterialTitle(event.target.value)} placeholder="素材标题，例如：订单系统重构" className="min-h-11" /><Textarea aria-label="素材结果" value={materialResult} onChange={(event) => setMaterialResult(event.target.value)} placeholder="记录可复用的结果、指标或证据" /><Button type="submit" variant="outline" className="min-h-11 self-start" disabled={!materialTitle.trim() || !materialResult.trim() || busyKey === "material"}>保存素材</Button></form>{materials.length === 0 ? <p className="text-[11.5px] text-ink-faint">把项目经历拆成可复用素材，后续生成岗位稿时可以再次引用。</p> : materials.slice(0, 5).map((material) => <div key={material.id} className="rounded-[8px] bg-surface-1 px-3 py-2"><div className="text-[12px] font-medium text-ink">{material.title}</div><div className="mt-1 line-clamp-2 text-[11.5px] text-ink-soft">{material.results}</div></div>)}</CardContent></Card>
            </div>
            <Card><CardHeader className="pb-2"><CardTitle>导出任务</CardTitle></CardHeader><CardContent>{exports.length === 0 ? <PanelEmpty>选择版本后创建批量导出任务。</PanelEmpty> : <div className="flex flex-col gap-2">{exports.slice(0, 6).map((job) => <div key={job.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] border border-[var(--border-soft)] px-3 py-2"><div className="text-[12px] text-ink"><span className="font-medium">{job.status === "done" ? "已完成" : job.status === "failed" ? "失败" : "处理中"}</span><span className="ml-2 text-ink-faint">{job.version_ids.length} 个版本 · {job.formats.join("/")}</span></div>{job.status === "done" && <Button variant="outline" size="sm" className="min-h-10 gap-1.5" disabled={busyKey === `download:${job.id}`} onClick={() => onDownload(job)}><Download className="h-3.5 w-3.5" />下载 ZIP</Button>}</div>)}</div>}</CardContent></Card>
          </>}
        </div>
      </div>
    </div>
  )
}

function ToolsPanel({ tools, calls, busyKey, isAdmin, onToggle }: { tools: ToolStatus[]; calls: ToolCall[]; busyKey: string | null; isAdmin: boolean; onToggle: (tool: ToolStatus) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <SectionHeading icon={<Wrench className="h-4 w-4" strokeWidth={1.7} />} title="工具中心" description="查看每个工具的配置、HITL 要求和健康状态；禁用策略由服务端强制生效。" />
      <Card>
        <CardHeader className="pb-2"><CardTitle>聊天模块工具</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2">
          {tools.length === 0 ? <PanelEmpty>当前模块没有可见工具，或服务端尚未加载配置。</PanelEmpty> : tools.map((tool) => (
            <div key={tool.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[8px] border border-[var(--border-soft)] px-3 py-3">
              <div className="flex min-w-0 items-start gap-2.5"><div className={cn("mt-0.5 h-2 w-2 shrink-0 rounded-full", tool.health === "ready" ? "bg-primary" : tool.health === "disabled" ? "bg-destructive" : "bg-amber-500")} /><div className="min-w-0"><div className="flex flex-wrap items-center gap-2 text-[12.5px] font-medium text-ink"><span>{tool.name}</span><StatusPill>{tool.kind === "mcp" ? "MCP" : "内部"}</StatusPill>{tool.requires_hitl && <StatusPill tone="warn">需人工确认</StatusPill>}</div><p className="mt-1 text-[11.5px] text-ink-soft">{tool.health_detail}</p></div></div>
              <div className="flex shrink-0 items-center gap-2"><StatusPill tone={tool.health === "ready" ? "ok" : tool.health === "disabled" ? "bad" : "warn"}>{tool.health === "ready" ? "就绪" : tool.health === "disabled" ? "已禁用" : "受限"}</StatusPill>{isAdmin ? <Button variant="outline" className="min-h-11" aria-label={`${tool.enabled ? "禁用" : "启用"} ${tool.name}`} disabled={busyKey === `tool:${tool.id}`} onClick={() => onToggle(tool)}>{tool.enabled ? "禁用" : "启用"}</Button> : <span className="text-[11px] text-ink-faint">仅管理员可修改</span>}</div>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card><CardHeader className="pb-2"><CardTitle>调用记录（已脱敏）</CardTitle></CardHeader><CardContent>{calls.length === 0 ? <PanelEmpty>还没有调用记录；输入问题并使用工具后，这里会显示状态和失败分类。</PanelEmpty> : <div className="flex flex-col gap-1.5">{calls.slice(0, 20).map((call) => <div key={call.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-soft)] py-2 last:border-b-0"><div className="flex items-center gap-2 text-[12px] text-ink"><span>{call.tool_id}</span>{call.requires_hitl && <StatusPill tone="warn">HITL {call.hitl_status || ""}</StatusPill>}</div><div className="text-[11px] text-ink-faint">{call.failure_category ? `失败：${call.failure_category}` : call.status || "已记录"} · {call.duration_ms ?? "—"} ms</div></div>)}</div>}</CardContent></Card>
      <div className="flex items-start gap-2 rounded-[9px] border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 text-[11.5px] leading-5 text-amber-800"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.7} />MCP 工具只展示服务端声明的受限状态，不在浏览器中直接探测或携带凭据。</div>
    </div>
  )
}
