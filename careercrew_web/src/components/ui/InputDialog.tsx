import { useEffect, useState } from "react"
import { Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/**
 * 输入弹窗（替代 window.prompt）：与 ConfirmDialog 同族的居中卡片，
 * 说明 + 输入框 + 弹窗内错误提示；Enter 提交，Esc / 遮罩取消。
 * onSubmit 返回错误文案则保持打开并红字提示，正常返回后自动关闭。
 */
export function InputDialog({
  open,
  title,
  message,
  placeholder,
  defaultValue = "",
  type = "text",
  confirmLabel = "确定",
  pendingLabel = "提交中…",
  autoComplete,
  onSubmit,
  onClose,
}: {
  open: boolean
  title: string
  message?: string
  placeholder?: string
  defaultValue?: string
  type?: "text" | "password"
  confirmLabel?: string
  pendingLabel?: string
  autoComplete?: string
  /** 校验/提交：返回错误文案表示失败（弹窗内提示），正常返回即关闭 */
  onSubmit: (value: string) => Promise<string | void> | string | void
  onClose: () => void
}) {
  const [value, setValue] = useState(defaultValue)
  const [error, setError] = useState("")
  const [pending, setPending] = useState(false)

  // 每次打开时重置内容与错误
  useEffect(() => {
    if (open) {
      setValue(defaultValue)
      setError("")
      setPending(false)
    }
  }, [open, defaultValue])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onClose()
      if (e.key === "Enter" && !e.isComposing && !pending) void submit()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pending, onClose, value])

  const submit = async () => {
    if (pending) return
    setPending(true)
    try {
      const err = await onSubmit(value)
      if (typeof err === "string" && err) {
        setError(err)
        return
      }
      onClose()
    } finally {
      setPending(false)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/25 p-4"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !pending) onClose()
      }}
    >
      <div className="stream-fade-in w-full max-w-[400px] rounded-[12px] border border-[var(--border-soft)] bg-workspace p-5 shadow-popover">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-[15px] font-medium text-ink">{title}</h3>
          <Tooltip label="关闭">
            <button
              type="button"
              onClick={onClose}
              disabled={pending}
              aria-label="关闭"
              className="shrink-0 rounded-[7px] p-1 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:opacity-50"
            >
              <X className="h-4 w-4" />
            </button>
          </Tooltip>
        </div>
        {message && <p className="mt-2 whitespace-pre-line text-[13px] leading-[1.55] text-ink-soft">{message}</p>}
        <input
          type={type}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            if (error) setError("")
          }}
          placeholder={placeholder}
          autoComplete={autoComplete}
          autoFocus
          disabled={pending}
          aria-invalid={error ? true : undefined}
          className={cn(
            "mt-3.5 h-[34px] w-full rounded-[7px] border bg-workspace px-2.5 text-[13px] text-ink outline-none transition-colors duration-100",
            "placeholder:text-ink-faint focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-60",
            error ? "border-destructive/60" : "border-input"
          )}
        />
        {error && (
          <p role="alert" className="mt-2 text-[12px] font-medium text-destructive">{error}</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>
            取消
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={pending}>
            {pending && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
            {pending ? pendingLabel : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
