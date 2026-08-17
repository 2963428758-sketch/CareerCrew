import { useEffect, useRef } from "react"
import { ChevronDown, ChevronUp, Search, X } from "lucide-react"

/**
 * 紧凑搜索条（§11.2）：keyword 输入 + 当前匹配序号/总数 + ↑ previous / ↓ next / Esc 关闭。
 * Codex 风格：30px 级紧凑操作，低存在感。作为 Workspace 内浮动条（绝对定位）挂载。
 */
export function ConversationSearchBar({
  open,
  keyword,
  currentIndex,
  total,
  onKeyword,
  onPrev,
  onNext,
  onClose,
}: {
  open: boolean
  keyword: string
  currentIndex: number
  total: number
  onKeyword: (v: string) => void
  onPrev: () => void
  onNext: () => void
  onClose: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  if (!open) return null

  const count = total > 0 ? `${currentIndex + 1} / ${total}` : "0 / 0"

  return (
    <div
      role="search"
      aria-label="会话搜索"
      className="absolute right-4 top-3 z-30 flex items-center gap-1 rounded-[9px] border border-[var(--border-soft)] bg-workspace px-1.5 py-1 shadow-popover"
    >
      <Search className="ml-1 h-3.5 w-3.5 shrink-0 text-ink-faint" strokeWidth={1.8} />
      <input
        ref={inputRef}
        value={keyword}
        onChange={(e) => onKeyword(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            if (e.shiftKey) onPrev()
            else onNext()
          }
        }}
        placeholder="搜索对话…"
        className="w-44 bg-transparent px-1 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
      />
      <span className="shrink-0 text-[11px] tabular-nums text-ink-faint">{count}</span>
      <button
        type="button"
        onClick={onPrev}
        disabled={total === 0}
        aria-label="上一个匹配"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-40"
      >
        <ChevronUp className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
      <button
        type="button"
        onClick={onNext}
        disabled={total === 0}
        aria-label="下一个匹配"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-40"
      >
        <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
      <button
        type="button"
        onClick={onClose}
        aria-label="关闭搜索"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
      >
        <X className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
    </div>
  )
}
