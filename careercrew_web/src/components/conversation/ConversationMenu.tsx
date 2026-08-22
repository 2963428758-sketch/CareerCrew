import { useEffect, useRef, useState } from "react"
import { Copy, Eraser, FileJson, FileText, MoreHorizontal, Pencil, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/ConfirmDialog"
import { useThreadStore } from "@/store/threadStore"
import { downloadBlob } from "@/lib/conversationExport"
import { copyText } from "@/components/conversation/copy"
import { notifyError, notifyInfo } from "@/lib/toastBus"
import { apiFetch } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

interface MenuEntryProps {
  icon: typeof Copy
  label: string
  danger?: boolean
  onClick: () => void
}

function MenuEntry({ icon: Icon, label, danger, onClick }: MenuEntryProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors duration-100",
        danger
          ? "text-destructive hover:bg-destructive/10"
          : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  )
}

/**
 * 会话菜单（顶部 …）：Rename / Copy ID / Export MD / Export JSON / Clear / Delete。
 *
 * 自包含下拉触发器 + 弹层 + 重命名内联输入 + 确认对话框。接线不需要依赖页面的
 * ConversationHeader——由调用方放在 header 的「更多」菜单里，或作为独立头按钮。
 */
export function ConversationMenu({
  threadId,
  title,
  module,
  onAfterClear,
}: {
  threadId: string
  title: string
  module: "chat" | "matcher" | "interview" | "knowledge" | "consult" | "resume"
  /** 清空/删除后由父组件刷新当前视图（可选） */
  onAfterClear?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(title)
  const [confirmClear, setConfirmClear] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [copied, setCopied] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setRenaming(false)
      }
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open])

  const close = () => {
    setOpen(false)
    setRenaming(false)
  }

  const handleRename = () => {
    const t = draft.trim()
    if (t && t !== title) void useThreadStore.getState().renameThread(module, threadId, t)
    close()
  }

  const handleCopyId = async () => {
    if (await copyText(threadId)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } else {
      notifyError(`复制失败，会话 ID：${threadId}`)
    }
  }

  const handleExport = async (format: "md" | "json") => {
    // 从后端导出（服务端为 Source of Truth，含 sources 与 run 元数据）
    try {
      const resp = await apiFetch(
        `/api/threads/${encodeURIComponent(threadId)}/export?format=${format}`
      )
      if (!resp.ok) throw new Error(await apiErrorText(resp, "导出失败"))
      const text = await resp.text()
      const safeTitle = (title || "conversation").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60)
      const filename = format === "md" ? `${safeTitle}.md` : `${safeTitle}.json`
      const mime = format === "md" ? "text/markdown;charset=utf-8" : "application/json;charset=utf-8"
      downloadBlob(text, mime, filename)
    } catch (e) {
      notifyError(networkErrorText(e, "导出失败"))
    }
  }

  const handleClear = async () => {
    try {
      const resp = await apiFetch(`/api/threads/${encodeURIComponent(threadId)}/clear`, {
        method: "POST",
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "清空失败"))
      notifyInfo("已清空会话消息")
      onAfterClear?.()
    } catch (e) {
      notifyError(networkErrorText(e, "清空失败"))
    }
  }

  const handleDelete = async () => {
    await useThreadStore.getState().deleteThread(module, threadId)
  }

  return (
    <div ref={ref} className="relative">
      <Tooltip label="更多" side="bottom">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label="更多"
          className={cn(
            "flex h-[30px] w-[30px] items-center justify-center rounded-[7px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink",
            open && "bg-[var(--active)] text-ink"
          )}
        >
          <MoreHorizontal className="h-4 w-4" strokeWidth={1.7} />
        </button>
      </Tooltip>

      {open && (
        <div className="absolute right-0 top-[34px] z-50 w-48 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover">
          {renaming ? (
            <div className="flex items-center gap-1 px-2 py-1.5">
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { handleRename(); close() }
                  if (e.key === "Escape") setRenaming(false)
                }}
                className="min-w-0 flex-1 rounded-[5px] border border-input bg-workspace px-1.5 py-0.5 text-[12px] text-ink outline-none"
                placeholder="新标题"
              />
            </div>
          ) : (
            <>
              <MenuEntry icon={Pencil} label="重命名" onClick={() => { setRenaming(true); setDraft(title) }} />
              <MenuEntry icon={Copy} label={copied ? "已复制 ✓" : "复制会话 ID"} onClick={handleCopyId} />
              <MenuEntry icon={FileText} label="导出 Markdown" onClick={() => { close(); void handleExport("md") }} />
              <MenuEntry icon={FileJson} label="导出 JSON" onClick={() => { close(); void handleExport("json") }} />
              <MenuEntry icon={Eraser} label="清空消息" onClick={() => { close(); setConfirmClear(true) }} />
              <MenuEntry icon={Trash2} label="删除会话" danger onClick={() => { close(); setConfirmDelete(true) }} />
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmClear}
        title="清空这个对话的消息？"
        message={`「${title}」的消息将被清空，但会话与标题会保留。此操作不可撤销。`}
        confirmLabel="清空"
        onConfirm={() => void handleClear()}
        onClose={() => setConfirmClear(false)}
      />
      <ConfirmDialog
        open={confirmDelete}
        title="删除这个对话？"
        message={`「${title}」删除后，该对话与记忆将无法恢复。`}
        confirmLabel="删除"
        onConfirm={() => void handleDelete()}
        onClose={() => setConfirmDelete(false)}
      />
    </div>
  )
}
