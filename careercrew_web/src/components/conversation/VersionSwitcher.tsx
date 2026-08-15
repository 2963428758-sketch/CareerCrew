import { ChevronLeft, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"

/**
 * 版本切换器（§19.2）：`< 1 / 2 >`，默认展示最新版本。
 * 纯展示/选择组件：只负责渲染当前版本号与前后切换按钮，
 * 内容切换由父级（TurnSection 渲染层）根据 selectedVersion 决定。
 */
export function VersionSwitcher({
  index,
  total,
  onPrev,
  onNext,
  className,
}: {
  /** 当前选中版本序号（1-based）。 */
  index: number
  /** 版本总数。 */
  total: number
  onPrev: () => void
  onNext: () => void
  className?: string
}) {
  if (total <= 1) return null

  const atOldest = index <= 1
  const atNewest = index >= total

  return (
    <div className={cn("flex items-center gap-1 text-[11.5px] text-ink-faint", className)}>
      <button
        type="button"
        aria-label="上一个版本"
        disabled={atOldest}
        onClick={onPrev}
        className="flex h-6 w-6 items-center justify-center rounded-[5px] transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-35"
      >
        <ChevronLeft className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
      <span className="select-none tabular-nums">
        {index} / {total}
      </span>
      <button
        type="button"
        aria-label="下一个版本"
        disabled={atNewest}
        onClick={onNext}
        className="flex h-6 w-6 items-center justify-center rounded-[5px] transition-colors duration-100 hover:bg-[var(--hover)] hover:text-ink disabled:pointer-events-none disabled:opacity-35"
      >
        <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
    </div>
  )
}
