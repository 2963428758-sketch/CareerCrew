import { useEffect } from "react"

/**
 * 确认对话框（Codex 风格，替代 window.confirm）：
 * 居中轻遮罩 + 12px 圆角面板；Esc / 点击遮罩取消；确认按钮为危险红。
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "删除",
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  message?: string
  confirmLabel?: string
  onConfirm: () => void
  onClose: () => void
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/25 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="stream-fade-in w-full max-w-[360px] rounded-[12px] border border-[var(--border-soft)] bg-workspace p-5 shadow-popover">
        <h3 className="text-[15px] font-medium text-ink">{title}</h3>
        {message && <p className="mt-2 text-[13px] leading-[1.55] text-ink-soft">{message}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-[30px] rounded-[7px] border border-input px-3 text-[13px] font-medium text-ink transition-colors duration-100 hover:bg-[var(--hover)]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => {
              onConfirm()
              onClose()
            }}
            className="h-[30px] rounded-[7px] bg-destructive px-3 text-[13px] font-medium text-destructive-foreground transition-opacity duration-100 hover:opacity-90"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
