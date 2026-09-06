import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Download, FileText, Loader2, Play } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { apiFetch } from "@/lib/auth"
import { networkErrorText } from "@/lib/errors"
import {
  createPrepSession,
  createVersion,
  downloadVersion,
  listVersions,
  type Opportunity,
  type ResumeVersion,
} from "@/lib/preparation"
import { useThreadStore } from "@/store/threadStore"

/** 把 blob 以指定文件名保存到本地（导出 PDF/DOCX 用）。 */
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

interface EditorState {
  label: string
  content: string
  originalContent: string
}

const EMPTY_EDITOR: EditorState = { label: "", content: "", originalContent: "" }

/**
 * 岗位专属简历工作台：
 * - 从简历库载入原文或粘贴原文，左侧原文 / 右侧当前稿对照编辑；
 * - 每次保存新增不可变版本；导出只针对已保存版本（PDF/DOCX）；
 * - 「开始简历定制 / 开始模拟面试」创建准备会话后跳转对应模块。
 */
export function ResumeWorkspace({ opportunity, onToast }: {
  opportunity: Opportunity
  onToast: (msg: string) => void
}) {
  const navigate = useNavigate()
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR)
  const [baseline, setBaseline] = useState<EditorState>(EMPTY_EDITOR)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [libraryBusy, setLibraryBusy] = useState(false)
  const [confirmSwitch, setConfirmSwitch] = useState<(() => void) | null>(null)
  const [confirmSession, setConfirmSession] = useState<"resume" | "interview" | null>(null)
  const oppIdRef = useRef(opportunity.id)
  oppIdRef.current = opportunity.id

  const dirty =
    editor.label !== baseline.label
    || editor.content !== baseline.content
    || editor.originalContent !== baseline.originalContent

  useEffect(() => {
    // 切换岗位：重载版本列表并清空编辑器
    setVersions([])
    setSelectedVersionId(null)
    setEditor(EMPTY_EDITOR)
    setBaseline(EMPTY_EDITOR)
    setError("")
    setVersionsLoading(true)
    let cancelled = false
    listVersions(opportunity.id)
      .then((rows) => {
        if (cancelled) return
        setVersions(rows)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : networkErrorText(e))
      })
      .finally(() => {
        if (!cancelled) setVersionsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [opportunity.id])

  /** 需要时先确认未保存修改，再执行目标动作。 */
  const guardUnsaved = (action: () => void) => {
    if (dirty) setConfirmSwitch(action)
    else action()
  }

  const loadVersion = (version: ResumeVersion) => {
    guardUnsaved(() => {
      const next: EditorState = {
        label: version.label,
        content: version.content,
        originalContent: version.original_content,
      }
      setSelectedVersionId(version.id)
      setEditor(next)
      setBaseline(next)
      setError("")
    })
  }

  const startNewDraft = () => {
    guardUnsaved(() => {
      setSelectedVersionId(null)
      setEditor(EMPTY_EDITOR)
      setBaseline(EMPTY_EDITOR)
    })
  }

  const handleSave = async () => {
    if (saving) return
    if (!editor.label.trim() || !editor.content.trim()) {
      setError("保存前请填写版本名称和简历内容")
      return
    }
    setSaving(true)
    setError("")
    try {
      // 保存失败（网络/校验）时编辑器内容保留，不丢草稿
      const saved = await createVersion(opportunity.id, {
        label: editor.label.trim(),
        content: editor.content,
        original_content: editor.originalContent,
      })
      setVersions((prev) => [saved, ...prev])
      setSelectedVersionId(saved.id)
      const next: EditorState = {
        label: saved.label,
        content: saved.content,
        originalContent: saved.original_content,
      }
      setEditor(next)
      setBaseline(next)
      onToast("简历版本已保存")
    } catch (e) {
      setError(e instanceof Error ? e.message : networkErrorText(e, "保存失败，请稍后重试"))
    } finally {
      setSaving(false)
    }
  }

  const handleExport = async (format: "pdf" | "docx") => {
    if (!selectedVersionId || busy) return
    setBusy(true)
    setError("")
    try {
      const blob = await downloadVersion(opportunity.id, selectedVersionId, format)
      const safeName = (editor.label.trim() || "简历").replace(/[/\\:*?"<>|]/g, "").trim() || "简历"
      saveBlob(blob, `${safeName}.${format}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : networkErrorText(e, "导出失败，请稍后重试"))
    } finally {
      setBusy(false)
    }
  }

  const handleStartSession = async (module: "resume" | "interview") => {
    if (!selectedVersionId || busy) return
    setBusy(true)
    setError("")
    try {
      const session = await createPrepSession(opportunity.id, module, selectedVersionId)
      const threads = useThreadStore.getState()
      threads.selectThread(module, session.thread_id)
      void threads.touchThread(
        module,
        session.thread_id,
        `${opportunity.company}·${opportunity.title}`,
      )
      onToast(module === "resume" ? "已创建简历定制会话" : "已创建模拟面试会话")
      navigate(module === "resume" ? "/resume" : "/interview")
    } catch (e) {
      setError(e instanceof Error ? e.message : networkErrorText(e, "创建会话失败，请稍后重试"))
    } finally {
      setBusy(false)
    }
  }

  /** 把指定已保存版本的内容复制进编辑器作为新草稿。 */
  const duplicateVersion = (version: ResumeVersion) => {
    guardUnsaved(() => {
      setSelectedVersionId(null)
      setEditor({
        label: `${version.label}（副本）`.slice(0, 120),
        content: version.content,
        originalContent: version.original_content,
      })
      setBaseline(EMPTY_EDITOR)
    })
  }

  /** 从简历库载入最新一份已上传简历的解析文本作为原文（覆盖前先确认未保存修改）。 */
  const loadFromLibrary = async () => {
    if (libraryBusy) return
    setLibraryBusy(true)
    setError("")
    try {
      const resp = await apiFetch("/api/resume/library")
      if (!resp.ok) throw new Error("简历库读取失败")
      const data = await resp.json() as { resumes?: Array<{ resume_id: string; filename?: string }> }
      const first = (data.resumes ?? [])[0]
      if (!first) {
        onToast("简历库为空，请先在简历页上传简历")
        return
      }
      const contentResp = await apiFetch(`/api/resume/library/${encodeURIComponent(first.resume_id)}/content`)
      if (!contentResp.ok) throw new Error("简历内容读取失败")
      const contentData = await contentResp.json() as { content?: string }
      const content = contentData.content ?? ""
      if (!content.trim()) {
        onToast("该简历内容为空")
        return
      }
      guardUnsaved(() => {
        setSelectedVersionId(null)
        setEditor({ label: "", content, originalContent: content })
        setBaseline(EMPTY_EDITOR)
        onToast(`已载入简历「${first.filename ?? first.resume_id}」，请编辑后保存为新版本`)
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : networkErrorText(e, "载入失败，请稍后重试"))
    } finally {
      setLibraryBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3" data-testid="resume-workspace">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[13.5px] font-[560] text-ink">简历版本</h3>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-[26px] text-[12px]"
            disabled={libraryBusy}
            onClick={() => void loadFromLibrary()}
          >
            {libraryBusy ? "载入中…" : "从简历库载入"}
          </Button>
          <Button variant="outline" size="sm" className="h-[26px] text-[12px]" onClick={startNewDraft}>
            新建草稿
          </Button>
          {versions.length > 0 && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="h-[26px] text-[12px]"
                disabled={!selectedVersionId || busy}
                onClick={() => handleExport("pdf")}
              >
                <Download className="h-3.5 w-3.5" /> 导出 PDF
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-[26px] text-[12px]"
                disabled={!selectedVersionId || busy}
                onClick={() => handleExport("docx")}
              >
                <Download className="h-3.5 w-3.5" /> 导出 DOCX
              </Button>
            </>
          )}
        </div>
      </div>

      {versionsLoading ? (
        <p className="flex items-center gap-1.5 text-[12px] text-ink-faint">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在加载版本…
        </p>
      ) : versions.length === 0 ? (
        <p className="text-[12px] text-ink-faint">
          还没有版本。从简历库载入或直接粘贴原文，编辑后保存第一个版本。
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {versions.map((v) => (
            <li key={v.id} className="flex items-center justify-between gap-2 text-[12.5px]">
              <button
                type="button"
                onClick={() => loadVersion(v)}
                className={
                  "min-w-0 flex-1 truncate rounded-md border px-2 py-1.5 text-left transition-colors " +
                  (selectedVersionId === v.id
                    ? "border-ink/50 bg-surface-2 text-ink"
                    : "border-[var(--border-soft)] bg-card text-ink-soft hover:border-ink-faint/60")
                }
              >
                <FileText className="mr-1 inline h-3 w-3" />
                {v.label}
                <span className="ml-2 text-[11px] text-ink-faint">
                  {new Date(v.created_at).toLocaleString()}
                </span>
              </button>
              <Button
                variant="ghost"
                size="sm"
                className="h-[24px] px-2 text-[11.5px]"
                onClick={() => duplicateVersion(v)}
              >
                复制为新稿
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
          原文（上传简历 / 上一版）
          <Textarea
            value={editor.originalContent}
            onChange={(e) => setEditor((s) => ({ ...s, originalContent: e.target.value }))}
            placeholder="粘贴简历原文，或从下方简历库载入"
            className="min-h-[220px] font-mono text-[12px]"
          />
        </label>
        <label className="flex flex-col gap-1 text-[12.5px] text-ink-soft">
          当前稿
          <Textarea
            value={editor.content}
            onChange={(e) => setEditor((s) => ({ ...s, content: e.target.value }))}
            placeholder="编辑当前简历稿"
            className="min-h-[220px] font-mono text-[12px]"
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[12.5px] text-ink-soft">
          版本名称
          <Input
            value={editor.label}
            onChange={(e) => setEditor((s) => ({ ...s, label: e.target.value }))}
            placeholder="例如：针对测试公司精简版"
            className="h-[30px] w-[220px]"
            maxLength={120}
          />
        </label>
        <Button size="sm" className="h-[28px] text-[12.5px]" disabled={saving} onClick={handleSave}>
          {saving ? "保存中…" : "保存为新版本"}
        </Button>
        {dirty && <span className="text-[11.5px] text-amber-600">有未保存的修改</span>}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border-soft)] pt-3">
        <Button
          variant="secondary"
          size="sm"
          className="h-[28px] text-[12.5px]"
          disabled={!selectedVersionId || busy}
          onClick={() => setConfirmSession("resume")}
        >
          <Play className="h-3.5 w-3.5" /> 开始简历定制
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="h-[28px] text-[12.5px]"
          disabled={!selectedVersionId || busy}
          onClick={() => setConfirmSession("interview")}
        >
          <Play className="h-3.5 w-3.5" /> 开始模拟面试
        </Button>
        <span className="text-[11.5px] text-ink-faint">将使用选定版本与该岗位 JD 创建准备会话</span>
      </div>

      {error && <p className="text-[12px] text-destructive">{error}</p>}

      <ConfirmDialog
        open={confirmSwitch !== null}
        title="放弃未保存的修改？"
        message="当前编辑内容尚未保存，继续将丢失这些修改。"
        confirmLabel="放弃修改"
        onConfirm={() => {
          const action = confirmSwitch
          setConfirmSwitch(null)
          action?.()
        }}
        onClose={() => setConfirmSwitch(null)}
      />
      <ConfirmDialog
        open={confirmSession !== null}
        title={confirmSession === "interview" ? "开始模拟面试？" : "开始简历定制？"}
        message={`将基于岗位「${opportunity.company} · ${opportunity.title}」与选定简历版本创建准备会话，JD 与简历将自动带入对话。`}
        confirmLabel="开始"
        onConfirm={() => {
          const target = confirmSession
          setConfirmSession(null)
          if (target) void handleStartSession(target)
        }}
        onClose={() => setConfirmSession(null)}
      />
    </div>
  )
}

export { saveBlob }
