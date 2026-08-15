import { useCallback, useEffect, useRef, useState } from "react"
import { BookmarkPlus, FileText, Loader2, Paperclip, Trash2, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import {
  deleteAttachment,
  listAttachments,
  pollSaveToKnowledge,
  saveAttachmentToKnowledge,
  uploadAttachment,
  validateAttachmentSelection,
  type Attachment,
  type AttachmentStatus,
} from "@/lib/attachments"

/** 状态 → 展示文案 + 颜色（与后端状态全集对齐，见 attachments.ts）。 */
const STATUS_META: Record<AttachmentStatus, { label: string; tone: string }> = {
  uploading: { label: "上传中", tone: "text-ink-soft" },
  uploaded: { label: "已上传", tone: "text-ink-soft" },
  parsing: { label: "解析中", tone: "text-ink-soft" },
  ready: { label: "已就绪", tone: "text-ink-soft" },
  failed: { label: "解析失败", tone: "text-destructive" },
  deleted: { label: "已删除", tone: "text-ink-faint" },
  saved_to_knowledge: { label: "已入知识库", tone: "text-ink-soft" },
}

/** ready 后可存入知识库（failed 允许重试，parsing 视作可再次触发但按钮禁用）。 */
function canSave(status: AttachmentStatus): boolean {
  return status === "uploaded" || status === "ready"
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export interface AttachmentPickerProps {
  /** 会话 thread_id（上传/列表必需）；由页面接线传入（defer 模式，见 brief）。 */
  threadId: string
  /** 附件列表/状态变化时回调（页面接线可据此把附件引用带进消息上下文）。 */
  onAttachmentsChange?: (attachments: Attachment[]) => void
  disabled?: boolean
}

/**
 * AttachmentPicker（T3.2 §35）：
 * 文件选择（客户端扩展名/大小预检）→ 上传（multipart）→ 状态 chips（含解析中/失败）
 * → 删除（二次确认）→ 「存入知识库」（ready 后可用，异步轮询刷新状态）。
 *
 * 自包含组件：不依赖全局 store，threadId 由父组件（PromptComposer 挂载处）传入。
 */
export function AttachmentPicker({
  threadId,
  onAttachmentsChange,
  disabled = false,
}: AttachmentPickerProps) {
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set())
  const [pendingDelete, setPendingDelete] = useState<Attachment | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const emit = useCallback(
    (next: Attachment[]) => {
      setAttachments(next)
      onAttachmentsChange?.(next)
    },
    [onAttachmentsChange]
  )

  const refresh = useCallback(async () => {
    try {
      emit(await listAttachments(threadId))
    } catch {
      // 初次加载失败静默；后续操作失败经 setError 提示
    }
  }, [threadId, emit])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleSelect = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setError(null)
    setUploading(true)
    try {
      const next = [...attachments]
      for (const file of Array.from(files)) {
        const precheck = validateAttachmentSelection(file.name, file.size)
        if (precheck) {
          setError(precheck)
          continue
        }
        const uploaded = await uploadAttachment(threadId, file)
        // 原位替换同 id（重复选择），否则追加
        const idx = next.findIndex((a) => a.id === uploaded.id)
        if (idx >= 0) next[idx] = uploaded
        else next.push(uploaded)
      }
      emit(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : "附件上传失败")
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ""
    }
  }

  const handleSave = async (att: Attachment) => {
    setSavingIds((prev) => new Set(prev).add(att.id))
    setError(null)
    try {
      await saveAttachmentToKnowledge(att.id)
      // 异步：轮询直到终态（saved_to_knowledge / failed / ready / deleted）
      const final = await pollSaveToKnowledge(threadId, att.id)
      // 用终态原位刷新本地列表，保证展示服务器最新状态
      emit(attachments.map((a) => (a.id === att.id ? final : a)))
      if (final.status === "failed") setError(final.parser_error || "解析失败，请重试")
    } catch (e) {
      setError(e instanceof Error ? e.message : "存入知识库失败")
    } finally {
      setSavingIds((prev) => {
        const next = new Set(prev)
        next.delete(att.id)
        return next
      })
    }
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    const id = pendingDelete.id
    setPendingDelete(null)
    try {
      await deleteAttachment(id)
      emit(attachments.filter((a) => a.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除附件失败")
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.pptx,.xlsx,.md,.txt,.png,.jpg,.jpeg"
        className="hidden"
        onChange={(e) => handleSelect(e.target.files)}
        data-testid="attachment-file-input"
      />

      <div className="flex items-center gap-1.5">
        <Tooltip label={disabled ? undefined : `添加附件（≤25MB，${5} 个/会话）`}>
          <button
            type="button"
            disabled={disabled || uploading}
            onClick={() => inputRef.current?.click()}
            aria-label="添加附件"
            className="flex h-[26px] w-[26px] items-center justify-center rounded-[6px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-50"
          >
            {uploading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Paperclip className="h-[15px] w-[15px]" strokeWidth={1.8} />
            )}
          </button>
        </Tooltip>
        {error && (
          <button
            type="button"
            onClick={() => setError(null)}
            className="inline-flex max-w-[calc(100%-40px)] items-center gap-1 truncate text-[11px] text-destructive"
          >
            <X className="h-3 w-3 shrink-0" />
            <span className="truncate">{error}</span>
          </button>
        )}
      </div>

      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="attachment-chips">
          {attachments.map((a) => {
            const meta = STATUS_META[a.status] ?? STATUS_META.uploaded
            const saving = savingIds.has(a.id)
            return (
              <div
                key={a.id}
                className={cn(
                  "flex items-center gap-1.5 rounded-[7px] border border-[var(--border-soft)] bg-surface-2 py-1 pl-2 pr-1 text-[12px]",
                  a.status === "failed" && "border-destructive/40"
                )}
                data-testid="attachment-chip"
              >
                <FileText className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                <span className="max-w-[140px] truncate text-ink" title={a.original_filename}>
                  {a.original_filename}
                </span>
                <span className="shrink-0 text-ink-faint">{formatSize(a.size_bytes)}</span>
                <span className={cn("shrink-0", meta.tone)}>
                  {saving ? "存入中…" : meta.label}
                </span>

                {canSave(a.status) && (
                  <Tooltip label="存入知识库">
                    <button
                      type="button"
                      aria-label={`将 ${a.original_filename} 存入知识库`}
                      disabled={saving}
                      onClick={() => handleSave(a)}
                      className="flex h-[22px] w-[22px] items-center justify-center rounded-[5px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:opacity-50"
                    >
                      <BookmarkPlus className="h-3.5 w-3.5" strokeWidth={1.8} />
                    </button>
                  </Tooltip>
                )}
                {a.status === "failed" && (
                  <Tooltip label="重试存入知识库">
                    <button
                      type="button"
                      aria-label={`重试 ${a.original_filename}`}
                      disabled={saving}
                      onClick={() => handleSave(a)}
                      className="flex h-[22px] w-[22px] items-center justify-center rounded-[5px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:opacity-50"
                    >
                      <Loader2 className="h-3.5 w-3.5" strokeWidth={1.8} />
                    </button>
                  </Tooltip>
                )}
                <Tooltip label="删除附件">
                  <button
                    type="button"
                    aria-label={`删除 ${a.original_filename}`}
                    onClick={() => setPendingDelete(a)}
                    className="flex h-[22px] w-[22px] items-center justify-center rounded-[5px] text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} />
                  </button>
                </Tooltip>
              </div>
            )
          })}
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="删除附件"
        message={pendingDelete ? `确认删除「${pendingDelete.original_filename}」？` : undefined}
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  )
}
