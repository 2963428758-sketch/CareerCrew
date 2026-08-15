import { useEffect, useRef, useState, type ReactNode } from "react"
import { Check, Copy, MoreHorizontal, RefreshCcw, ThumbsDown, ThumbsUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { copyText } from "@/components/conversation/copy"
import { Tooltip } from "@/components/ui/tooltip"
import type { MessageFeedback } from "@/types"

function ActionButton({
  title,
  active = false,
  hoverReveal = false,
  onClick,
  children,
}: {
  title: string
  active?: boolean
  hoverReveal?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Tooltip label={title}>
      <button
        type="button"
        aria-label={title}
        aria-pressed={active || undefined}
        onClick={onClick}
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-[6px] transition-colors duration-100",
          "text-ink-faint hover:bg-[var(--hover)] hover:text-ink",
          active && "bg-[var(--active)] text-ink",
          hoverReveal && "opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-100"
        )}
      >
        {children}
      </button>
    </Tooltip>
  )
}

/**
 * Agent 回答操作栏（28px 高）：
 * Copy / 👍 / 👎 常显（低透明度）；↻ 重新生成 / ⋯ 更多在 Hover 后出现。
 * §17：只有 completed 回答才显示 👍/👎/↻（streaming 中隐藏）；Copy 仍可用。
 * §18：Copy 成功后短暂显示 Check（1.5s）；More 菜单含「复制消息 ID」。
 */
export function MessageActions({
  content,
  feedback,
  completed = true,
  messageId,
  onCopy,
  onToggleLike,
  onToggleDislike,
  onRegenerate,
}: {
  content: string
  feedback: MessageFeedback | null
  /** 是否为已完成回答；false（streaming）时隐藏 👍/👎/↻。 */
  completed?: boolean
  /** 后端稳定 message_id：More 菜单「复制消息 ID」所用（缺失则该项隐藏）。 */
  messageId?: string
  onCopy: () => void
  onToggleLike: () => void
  onToggleDislike: () => void
  onRegenerate?: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
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
    onCopy()
  }

  return (
    <div ref={rootRef} className="relative mt-2.5 flex h-7 items-center gap-0.5">
      <ActionButton title="复制回答" onClick={handleCopy}>
        {copied ? <Check className="h-[15px] w-[15px]" strokeWidth={1.8} /> : <Copy className="h-[15px] w-[15px]" strokeWidth={1.8} />}
      </ActionButton>
      {completed && (
        <>
          <ActionButton
            title={feedback?.rating === "positive" ? "取消反馈" : "有帮助"}
            active={feedback?.rating === "positive"}
            onClick={onToggleLike}
          >
            <ThumbsUp className="h-[15px] w-[15px]" strokeWidth={1.8} />
          </ActionButton>
          <ActionButton
            title={feedback?.rating === "negative" ? "取消反馈" : "不满意"}
            active={feedback?.rating === "negative"}
            onClick={onToggleDislike}
          >
            <ThumbsDown className="h-[15px] w-[15px]" strokeWidth={1.8} />
          </ActionButton>
        </>
      )}
      {completed && onRegenerate && (
        <ActionButton title="重新生成" hoverReveal onClick={onRegenerate}>
          <RefreshCcw className="h-[15px] w-[15px]" strokeWidth={1.8} />
        </ActionButton>
      )}
      {messageId && (
        <ActionButton title="更多" hoverReveal onClick={() => setMenuOpen((o) => !o)}>
          <MoreHorizontal className="h-[15px] w-[15px]" strokeWidth={1.8} />
        </ActionButton>
      )}

      {menuOpen && (
        <div className="absolute bottom-9 left-0 z-50 w-40 overflow-hidden rounded-[9px] border border-[var(--border-soft)] bg-workspace py-1 shadow-popover">
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false)
              void handleCopy()
            }}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
          >
            <Copy className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">复制回答</span>
          </button>
          {messageId && (
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false)
                void copyText(messageId)
              }}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
            >
              <Copy className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">复制消息 ID</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}
