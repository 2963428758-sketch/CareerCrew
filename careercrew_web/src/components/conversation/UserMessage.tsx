import { memo, useEffect, useRef, useState } from "react"
import { Check, Copy, FileImage, FileText, MoreHorizontal, Pencil } from "lucide-react"
import { cn } from "@/lib/utils"
import { copyText } from "@/components/conversation/copy"
import { Tooltip } from "@/components/ui/tooltip"
import { useThreadStore } from "@/store/threadStore"
import type { MessageAttachment } from "@/types"

/**
 * 用户消息气泡（Codex 风格）：右对齐、弱灰、轻微不对称圆角（右下 5px）。
 * Hover 时左下浮现 Copy / Edit / ⋯ 操作；Copy 成功后图标短暂变为 Check（1.5s）。
 * memo：流式/输入引发的高频父级重渲染在 props 不变时 bail out。
 */
export const UserMessage = memo(function UserMessage({
  content,
  turnId,
  highlighted = false,
  onEdit,
  attachments,
  className,
}: {
  content: string
  /** turn anchor id（= 用户消息 id），rail 与 IO 据此定位 */
  turnId?: string
  highlighted?: boolean
  onEdit?: (text: string) => void
  attachments?: MessageAttachment[]
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuCoords, setMenuCoords] = useState<{ top: number; right: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [menuOpen])

  const handleCopy = async () => {
    if (await copyText(content)) {
      setCopied(true)
      timerRef.current = setTimeout(() => setCopied(false), 1500)
    }
  }

  const handleMore = () => {
    const el = rootRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    // 菜单锚在气泡右下方；若视口空间不足则向上展开
    const spaceBelow = window.innerHeight - r.bottom
    setMenuCoords({
      top: spaceBelow > 150 ? r.bottom + 4 : r.top - 4,
      right: window.innerWidth - r.right,
    })
    setMenuOpen((o) => !o)
  }

  const copyThreadId = () => {
    setMenuOpen(false)
    const tid = useThreadStore.getState().currentThreadByModule.chat
    if (tid) void useThreadStore.getState().copyThreadId(tid)
  }

  return (
    <div ref={rootRef} className={cn("group relative flex flex-col items-end", className)}>
      {attachments && attachments.length > 0 && (
        <div
          className="mb-1.5 flex max-w-[68%] flex-wrap justify-end gap-1.5 max-md:max-w-[84%]"
          data-testid="message-attachments"
        >
          {attachments.map((attachment) => {
            const isImage = attachment.kind === "image"
              || attachment.mimeType?.startsWith("image/")
              || /\.(png|jpe?g)$/i.test(attachment.filename)
            const Icon = isImage ? FileImage : FileText
            return (
              <div
                key={attachment.id}
                className="flex min-w-0 items-center gap-1.5 rounded-[8px] border border-[var(--border-soft)] bg-surface-2 px-2 py-1.5 text-[12px] text-ink-soft"
                data-testid="message-attachment"
                title={attachment.filename}
              >
                <Icon className="h-3.5 w-3.5 shrink-0 text-ink-soft" strokeWidth={1.8} />
                <span className="max-w-[180px] truncate">{attachment.filename}</span>
                {typeof attachment.sizeBytes === "number" && (
                  <span className="shrink-0 text-[11px] text-ink-faint">
                    {formatAttachmentSize(attachment.sizeBytes)}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
      <div
        data-turn-anchor={turnId}
        data-testid="user-message-bubble"
        className={cn(
          "max-w-[68%] max-md:max-w-[84%] whitespace-pre-wrap rounded-[14px_14px_5px_14px] bg-[var(--user-bubble)] px-3.5 py-2.5 text-[14px] leading-[1.55] text-ink",
          highlighted && "anchor-highlight"
        )}
      >
        {content}
      </div>

      {/* 操作行：默认透明，Hover 气泡时浮现（移动端 Copy 常显） */}
      <div className="absolute -bottom-6 right-0 flex items-center gap-0.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        <Tooltip label="复制">
          <button
            type="button"
            onClick={handleCopy}
            aria-label="复制"
            className="flex h-6 items-center gap-1 rounded-[5px] px-1.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink max-md:opacity-100"
          >
            {copied ? <Check className="h-3.5 w-3.5" strokeWidth={1.8} /> : <Copy className="h-3.5 w-3.5" strokeWidth={1.8} />}
          </button>
        </Tooltip>
        {onEdit && (
          <Tooltip label="编辑">
            <button
              type="button"
              onClick={() => onEdit(content)}
              aria-label="编辑"
              className="flex h-6 items-center gap-1 rounded-[5px] px-1.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
            >
              <Pencil className="h-3.5 w-3.5" strokeWidth={1.8} />
            </button>
          </Tooltip>
        )}
        <Tooltip label="更多">
          <button
            type="button"
            onClick={handleMore}
            aria-label="更多"
            className="flex h-6 items-center gap-1 rounded-[5px] px-1.5 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
          >
            <MoreHorizontal className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
        </Tooltip>
      </div>

      {menuOpen && menuCoords && (
        <div
          className="fixed z-50 w-36 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover"
          style={{ top: menuCoords.top, right: menuCoords.right }}
        >
          <button
            type="button"
            onClick={copyThreadId}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
          >
            <Copy className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">复制会话 ID</span>
          </button>
        </div>
      )}
    </div>
  )
})

function formatAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
