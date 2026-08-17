import { useEffect, useState } from "react"
import { Send, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip } from "@/components/ui/tooltip"
import type { ConsultInputField } from "@/types"
import { CONSULT_INPUT_FIELDS } from "@/types"
import { cn } from "@/lib/utils"

interface ConsultFormDialogProps {
  open: boolean
  /** 总调度官/顾问的引导语（说明为什么需要这些信息）。 */
  message?: string
  /** 需要填写的字段；为空时使用前端兜底字段（CONSULT_INPUT_FIELDS）。 */
  fields: ConsultInputField[]
  onClose: () => void
  /** 提交回调：values 为字段 id -> 填写内容（含空串）。 */
  onSubmit: (values: Record<string, string>) => void
  submitting?: boolean
}

export function ConsultFormDialog({
  open,
  message,
  fields,
  onClose,
  onSubmit,
  submitting,
}: ConsultFormDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  // 每次打开时清空上一次的填写内容与校验错误
  useEffect(() => {
    if (open) {
      setValues({})
      setErrors({})
    }
  }, [open])

  if (!open) return null

  const resolved: ConsultInputField[] = fields.length > 0 ? fields : CONSULT_INPUT_FIELDS

  const submit = () => {
    const nextErrors: Record<string, string> = {}
    for (const f of resolved) {
      if (f.required && !(values[f.id] ?? "").trim()) {
        nextErrors[f.id] = "请填写此项"
      }
    }
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) return
    onSubmit({ ...values })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-[12px] border border-[var(--border-soft)] bg-workspace shadow-popover stream-fade-in">
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border-soft)] px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-[15px] font-medium text-ink">补充你的求职信息</h3>
            {message && <p className="mt-1 line-clamp-3 text-[12.5px] text-ink-soft">{message}</p>}
          </div>
          <Tooltip label="稍后填写">
            <button
              onClick={onClose}
              aria-label="稍后填写"
              className="shrink-0 rounded-[7px] p-1 text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
            >
              <X className="h-4 w-4" />
            </button>
          </Tooltip>
        </div>

        <div className="max-h-[55vh] space-y-3 overflow-y-auto px-5 py-4">
          {resolved.map((f) => (
            <label key={f.id} className="block">
              <span className="mb-1 flex items-center gap-1 text-[12.5px] font-medium text-ink">
                {f.label}
                {f.required && <span className="text-destructive">*</span>}
              </span>
              <input
                value={values[f.id] ?? ""}
                onChange={(e) => {
                  setValues((v) => ({ ...v, [f.id]: e.target.value }))
                  if (errors[f.id]) setErrors((er) => ({ ...er, [f.id]: "" }))
                }}
                placeholder={f.placeholder}
                autoFocus={f.id === resolved[0]?.id}
                className={cn(
                  "h-9 w-full rounded-[7px] border bg-workspace px-3 text-[13px] outline-none transition-colors duration-100",
                  "placeholder:text-ink-faint focus-visible:ring-2 focus-visible:ring-ring/40",
                  errors[f.id] ? "border-destructive" : "border-input"
                )}
              />
              {errors[f.id] && (
                <span className="mt-1 block text-[11px] text-destructive">{errors[f.id]}</span>
              )}
            </label>
          ))}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-soft)] px-5 py-3">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={submitting}>
            稍后填写
          </Button>
          <Button size="sm" onClick={submit} disabled={submitting}>
            <Send className="mr-1.5 h-3.5 w-3.5" />
            {submitting ? "提交中…" : "提交并继续"}
          </Button>
        </div>
      </div>
    </div>
  )
}
