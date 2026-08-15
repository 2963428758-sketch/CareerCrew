import { useEffect, useRef, useState } from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"
import type { MessageFeedback } from "@/types"

const FEEDBACK_REASONS: { id: NonNullable<MessageFeedback["reason"]>; label: string }[] = [
  { id: "incorrect", label: "信息有误" },
  { id: "not_helpful", label: "对我没有帮助" },
  { id: "did_not_answer", label: "没有回答我的问题" },
  { id: "too_verbose", label: "回答过于冗长" },
  { id: "hard_to_understand", label: "难以理解" },
  { id: "other", label: "其他" },
]

/**
 * 点踩反馈 Popover（非 Modal）：选原因 + 可选补充说明 → 提交。
 * 点击外部 / Esc 关闭；打开时记录参考锚点，关闭后恢复焦点。
 */
export function FeedbackPopover({
  open,
  onClose,
  onSubmit,
  className,
}: {
  open: boolean
  onClose: () => void
  onSubmit: (reason: NonNullable<MessageFeedback["reason"]>, comment: string) => void
  className?: string
}) {
  const [reason, setReason] = useState<NonNullable<MessageFeedback["reason"]>>("not_helpful")
  const [comment, setComment] = useState("")
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={ref}
      className={cn(
        "absolute bottom-full left-0 z-50 mb-1.5 w-[300px] max-w-[calc(100vw-32px)] rounded-[10px] border border-[var(--border-normal)] bg-workspace p-3 shadow-popover",
        className
      )}
    >
      <p className="mb-2 text-[12.5px] font-medium text-ink">哪里可以改进？</p>
      <div className="flex flex-col gap-0.5">
        {FEEDBACK_REASONS.map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => setReason(r.id)}
            className={cn(
              "flex items-center justify-between gap-2 rounded-[6px] px-2 py-1.5 text-left text-[12.5px] transition-colors duration-100",
              reason === r.id ? "bg-[var(--hover)] text-ink" : "text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
            )}
          >
            <span>{r.label}</span>
            {reason === r.id && <Check className="h-3.5 w-3.5 shrink-0 text-ink-soft" strokeWidth={1.8} />}
          </button>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="补充说明（可选）"
        rows={2}
        className="mt-2 block w-full resize-none rounded-[7px] border border-input bg-transparent px-2 py-1.5 text-[12.5px] leading-[1.5] text-ink outline-none placeholder:text-ink-faint focus:border-[var(--border-strong)]"
      />
      <div className="mt-2 flex items-center justify-end gap-1.5">
        <button
          type="button"
          onClick={onClose}
          className="h-7 rounded-[7px] px-2 text-[12px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => onSubmit(reason, comment.trim())}
          className="h-7 rounded-[7px] bg-button-ink px-2.5 text-[12px] font-medium text-button-onink transition-opacity duration-100 hover:opacity-90"
        >
          提交
        </button>
      </div>
    </div>
  )
}
