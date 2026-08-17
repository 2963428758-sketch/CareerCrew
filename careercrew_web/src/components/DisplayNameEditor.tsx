import { useState } from "react"
import { Check, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { apiFetch, updateSessionUser } from "@/lib/auth"
import { apiErrorText, networkErrorText } from "@/lib/errors"

/**
 * 显示名内联编辑器：输入 + 保存/取消（Enter 保存、Esc 取消）。
 * 保存成功后通过 updateSessionUser 同步全局登录态，父组件用 onDone 收起编辑态。
 */
export function NameEditor({
  current,
  onDone,
  inputClassName,
}: {
  current: string
  onDone?: () => void
  inputClassName?: string
}) {
  const [draft, setDraft] = useState(current)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  const save = async () => {
    const name = draft.trim()
    if (!name || name === current) {
      onDone?.()
      return
    }
    setSaving(true)
    setError("")
    try {
      const resp = await apiFetch("/api/auth/display-name", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
      if (!resp.ok) throw new Error(await apiErrorText(resp, "保存名字失败，请重试"))
      const updated = await resp.json() as { display_name?: string | null }
      updateSessionUser({ display_name: updated.display_name ?? name })
      onDone?.()
    } catch (e) {
      setError(networkErrorText(e, "保存失败，请检查网络后重试"))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-center gap-1">
        <input
          autoFocus
          value={draft}
          maxLength={30}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save()
            if (e.key === "Escape") onDone?.()
          }}
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "min-w-0 flex-1 rounded-[5px] border border-input bg-workspace px-1.5 py-0.5 text-[13px] text-ink outline-none",
            inputClassName
          )}
        />
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          aria-label="保存名字"
          className="rounded-[5px] p-1 text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:opacity-50"
        >
          <Check className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => onDone?.()}
          aria-label="取消"
          className="rounded-[5px] p-1 text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {error && <p className="mt-0.5 text-[11px] text-destructive">{error}</p>}
    </div>
  )
}
