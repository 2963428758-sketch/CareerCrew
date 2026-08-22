import { useEffect } from "react"
import { Loader2 } from "lucide-react"

/**
 * 确认对话框（Codex 风格，替代 window.confirm）：
 * 居中轻遮罩 + 12px 圆角面板；Esc / 点击遮罩取消；确认按钮为危险红。
 * pending 为 true 时进入「进行中」状态：禁用全部交互并展示 pendingLabel，
 * 供删除账号等需要清理数据、耗时较长的异步操作使用（由父组件在完成后关闭）。
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "删除",
  pendingLabel,
  pending = false,
  closeOnConfirm = true,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  message?: string
  confirmLabel?: string
  /** 操作进行中的按钮文案（如「删除中…」） */
  pendingLabel?: string
  /** 异步操作进行中：禁用取消/确认并阻止 Esc、遮罩关闭 */
  pending?: boolean
  /** 点击确认后是否由本组件立即关闭；异步操作传 false，父组件完成后自行关闭 */
  closeOnConfirm?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, pending, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/25 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !pending) onClose()
      }}
    >
      <div className="stream-fade-in w-full max-w-[360px] rounded-[12px] border border-[var(--border-soft)] bg-workspace p-5 shadow-popover">
        <h3 className="text-[15px] font-medium text-ink">{title}</h3>
        {message && <p className="mt-2 text-[13px] leading-[1.55] text-ink-soft">{message}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            className="h-[30px] rounded-[7px] border border-input px-3 text-[13px] font-medium text-ink transition-colors duration-100 hover:bg-[var(--hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              onConfirm()
              if (closeOnConfirm) onClose()
            }}
            className="inline-flex h-[30px] items-center gap-1.5 rounded-[7px] bg-destructive px-3 text-[13px] font-medium text-destructive-foreground transition-opacity duration-100 hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending && <Loader2 className="h-3 w-3 animate-spin" />}
            {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
