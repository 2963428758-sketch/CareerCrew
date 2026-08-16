import { useCallback, useEffect, useRef, useState } from "react"
import { Loader2, ShieldAlert, Wrench, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import {
  fetchAgentCapabilities,
  resolveSelectedToolIds,
  toolDisplayName,
  type ToolCapability,
} from "@/lib/agentCapabilities"

export interface ToolPickerProps {
  /** 已选工具变化回调（页面接线把 tools 带进请求体）。 */
  onToolsChange?: (toolIds: string[]) => void
  /** 拉取 capability 的 module（默认 chat）。 */
  module?: string
  disabled?: boolean
}

/**
 * ToolPicker（T3.5 §16）：
 * 从服务端 capability 拉取可见工具 → 多选（勾选/取消）→ chips 展示。
 * 客户端只选择「允许使用哪些 Tool」，不等同于立即执行（§16.2）；最终集合由服务端
 * effective_tools 裁剪（§16.3），选择永远不能突破 server allowlist。
 */
export function ToolPicker({ onToolsChange, module = "chat", disabled = false }: ToolPickerProps) {
  const [open, setOpen] = useState(false)
  const [caps, setCaps] = useState<ToolCapability[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const boxRef = useRef<HTMLDivElement>(null)
  const reqSeq = useRef(0)

  const emit = useCallback(
    (next: string[]) => {
      setSelected(next)
      onToolsChange?.([...next])
    },
    [onToolsChange]
  )

  const load = useCallback(async () => {
    const seq = ++reqSeq.current
    setLoading(true)
    setError(null)
    try {
      const rows = await fetchAgentCapabilities(module)
      if (seq === reqSeq.current) setCaps(rows)
    } catch (e) {
      if (seq === reqSeq.current) setError(e instanceof Error ? e.message : "加载工具能力失败")
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }, [module])

  // 首次打开时拉取（能力列表稳定，服务端单一事实来源）；失败可重试。
  const toggleOpen = () => {
    setOpen((o) => !o)
    if (!caps.length && !loading) void load()
  }

  const toggle = (cap: ToolCapability) => {
    if (!cap.enabled) return
    const next = selected.includes(cap.id)
      ? selected.filter((x) => x !== cap.id)
      : [...selected, cap.id]
    emit(resolveSelectedToolIds(caps, next))
  }

  const remove = (id: string) => {
    emit(selected.filter((x) => x !== id))
  }

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [])

  return (
    <div className="relative" ref={boxRef}>
      <div className="flex items-center gap-1.5">
        <Tooltip label={disabled ? undefined : "选择本轮允许使用的工具"}>
          <button
            type="button"
            disabled={disabled}
            aria-label="工具"
            onClick={toggleOpen}
            className="flex h-[26px] w-[26px] items-center justify-center rounded-[6px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-50"
          >
            <Wrench className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
        </Tooltip>
        {error && (
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex max-w-[calc(100%-40px)] items-center gap-1 truncate text-[11px] text-destructive"
          >
            <X className="h-3 w-3 shrink-0" />
            <span className="truncate">{error}（重试）</span>
          </button>
        )}
      </div>

      {open && (
        <div className="absolute bottom-[30px] left-0 z-30 w-[260px] rounded-[10px] border border-[var(--border-soft)] bg-surface-2 p-1.5 shadow-prompt">
          <div className="max-h-[240px] overflow-y-auto" data-testid="tool-results">
            {loading && caps.length === 0 && (
              <div className="flex items-center gap-1.5 px-2 py-2 text-[12px] text-ink-faint">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载中…
              </div>
            )}
            {!loading && caps.length === 0 && !error && (
              <div className="px-2 py-2 text-[12px] text-ink-faint">无可选工具</div>
            )}
            {caps.map((cap) => {
              const checked = selected.includes(cap.id)
              return (
                <button
                  key={cap.id}
                  type="button"
                  disabled={!cap.enabled}
                  onClick={() => toggle(cap)}
                  data-testid="tool-option"
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded-[6px] px-2 py-1.5 text-left text-[12.5px] transition-colors duration-100 hover:bg-[var(--hover)]",
                    checked && "bg-[var(--active)]",
                    !cap.enabled && "opacity-50"
                  )}
                >
                  <Wrench className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                  <span className="max-w-[140px] truncate text-ink" title={cap.id}>
                    {toolDisplayName(cap)}
                  </span>
                  {cap.requires_hitl && (
                    <ShieldAlert
                      className="ml-auto h-3.5 w-3.5 shrink-0 text-amber-500"
                      strokeWidth={1.8}
                      aria-label="需人工确认"
                    />
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {selected.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5" data-testid="tool-chips">
          {selected.map((id) => {
            const cap = caps.find((c) => c.id === id)
            return (
              <div
                key={id}
                className="flex items-center gap-1 rounded-[7px] border border-[var(--border-soft)] bg-surface-2 py-1 pl-2 pr-1 text-[12px]"
                data-testid="tool-chip"
              >
                <span className="text-ink-faint">🔧</span>
                <span className="max-w-[140px] truncate text-ink" title={id}>
                  {cap ? toolDisplayName(cap) : id}
                </span>
                <button
                  type="button"
                  aria-label={`移除 ${cap ? toolDisplayName(cap) : id}`}
                  onClick={() => remove(id)}
                  className="flex h-[22px] w-[22px] items-center justify-center rounded-[5px] text-ink-faint transition-colors duration-100 hover:bg-[var(--hover)] hover:text-destructive"
                >
                  <X className="h-3.5 w-3.5" strokeWidth={1.8} />
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
