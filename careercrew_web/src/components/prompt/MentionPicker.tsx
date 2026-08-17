import { useCallback, useEffect, useRef, useState } from "react"
import { FileText, Loader2, Search, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import {
  debounce,
  fetchContextResources,
  MENTION_TYPE_LABEL,
  type ContextResource,
  type Mention,
} from "@/lib/contextResources"

export interface MentionPickerProps {
  /** 已选 mention 变化回调（页面接线把 mention 引用带进请求体）。 */
  onMentionsChange?: (mentions: Mention[]) => void
  disabled?: boolean
}

/**
 * MentionPicker（T3.4 §15）：
 * 输入关键词 → 防抖搜索可引用资源（knowledge_document / resume）→ 下拉选择 →
 * chips 展示选中项（可删除）。自包含组件，不依赖全局 store。
 *
 * 仅列出服务端已过 visibility + ownership 过滤的资源；提交时后端会再校验。
 */
export function MentionPicker({ onMentionsChange, disabled = false }: MentionPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [items, setItems] = useState<ContextResource[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Mention[]>([])
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  // latest-wins：滚动/关闭后忽略过期响应
  const reqSeq = useRef(0)

  const emit = useCallback(
    (next: Mention[]) => {
      setSelected(next)
      onMentionsChange?.(next)
    },
    [onMentionsChange]
  )

  const runSearch = useCallback(async (q: string) => {
    const seq = ++reqSeq.current
    setLoading(true)
    setError(null)
    try {
      const rows = await fetchContextResources({ q })
      if (seq === reqSeq.current) setItems(rows)
    } catch (e) {
      if (seq === reqSeq.current) setError(e instanceof Error ? e.message : "加载可引用资源失败")
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }, [])

  // 防抖：输入变化后 250ms 才搜索
  const debouncedSearch = useRef(debounce((q: string) => { void runSearch(q) }, 250)).current

  const handleQuery = (q: string) => {
    setQuery(q)
    debouncedSearch(q)
  }

  const toggle = (r: ContextResource) => {
    const exists = selected.some((m) => m.type === r.type && m.id === r.id)
    if (exists) {
      emit(selected.filter((m) => !(m.type === r.type && m.id === r.id)))
    } else {
      emit([...selected, { type: r.type, id: r.id }])
    }
    // 保持下拉打开，关闭错误提示
    setError(null)
  }

  const remove = (m: Mention) => {
    emit(selected.filter((x) => !(x.type === m.type && x.id === m.id)))
  }

  // 点击外部关闭
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
        <Tooltip label={disabled ? undefined : "引用资料（@ 知识文档 / 简历）"}>
          <button
            type="button"
            disabled={disabled}
            aria-label="引用资料"
            onClick={() => {
              setOpen((o) => !o)
              if (!open) inputRef.current?.focus()
            }}
            className="flex h-[26px] w-[26px] items-center justify-center rounded-[6px] text-ink-soft transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-50"
          >
            <Search className="h-[15px] w-[15px]" strokeWidth={1.8} />
          </button>
        </Tooltip>
        {error && (
          <button
            type="button"
            onClick={() => setError(null)}
            className="inline-flex max-w-[calc(100%-40px)] items-center gap-1 truncate text-[11px] text-destructive"
          >
            <X className="h-3 w-3 shrink-0" />
            <span className="truncate">{error}</span>
          </button>
        )}
      </div>

      {open && (
        <div className="absolute bottom-[30px] left-0 z-30 w-[280px] rounded-[10px] border border-[var(--border-soft)] bg-surface-2 p-1.5 shadow-prompt">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => handleQuery(e.target.value)}
              placeholder="搜索知识文档或简历…"
              data-testid="mention-search-input"
              className="h-8 w-full rounded-[7px] border border-[var(--border-soft)] bg-surface-1 pl-7 pr-2 text-[12.5px] outline-none placeholder:text-ink-faint focus:border-[var(--border-strong)]"
            />
          </div>

          <div className="mt-1 max-h-[240px] overflow-y-auto" data-testid="mention-results">
            {loading && items.length === 0 && (
              <div className="flex items-center gap-1.5 px-2 py-2 text-[12px] text-ink-faint">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> 搜索中…
              </div>
            )}
            {!loading && items.length === 0 && (
              <div className="px-2 py-2 text-[12px] text-ink-faint">无匹配资源</div>
            )}
            {items.map((r) => {
              const checked = selected.some((m) => m.type === r.type && m.id === r.id)
              return (
                <button
                  key={`${r.type}:${r.id}`}
                  type="button"
                  onClick={() => toggle(r)}
                  data-testid="mention-result"
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded-[6px] px-2 py-1.5 text-left text-[12.5px] transition-colors duration-100 hover:bg-[var(--hover)]",
                    checked && "bg-[var(--active)]"
                  )}
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-ink-soft" />
                  <span className="max-w-[150px] truncate text-ink" title={r.name}>{r.name}</span>
                  <span className="ml-auto shrink-0 rounded-[4px] bg-surface-3 px-1 text-[10px] text-ink-faint">
                    {MENTION_TYPE_LABEL[r.type]}
                  </span>
                  {r.visibility === "public" && (
                    <span className="shrink-0 rounded-[4px] bg-surface-3 px-1 text-[10px] text-ink-faint">公开</span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {selected.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5" data-testid="mention-chips">
          {selected.map((m) => {
            const label = items.find((r) => r.type === m.type && r.id === m.id)?.name || m.id
            return (
              <div
                key={`${m.type}:${m.id}`}
                className="flex items-center gap-1 rounded-[7px] border border-[var(--border-soft)] bg-surface-2 py-1 pl-2 pr-1 text-[12px]"
                data-testid="mention-chip"
              >
                <span className="text-ink-faint">@</span>
                <span className="max-w-[140px] truncate text-ink" title={label}>{label}</span>
                <button
                  type="button"
                  aria-label={`移除 ${label}`}
                  onClick={() => remove(m)}
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
