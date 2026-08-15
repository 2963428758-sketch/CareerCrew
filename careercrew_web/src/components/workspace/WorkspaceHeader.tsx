import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * Workspace 头部（Codex 风格）：50px 单行。
 * 左侧面包屑：父级 13px 淡墨 / 当前页 13px weight 500；右侧 30px 级操作区。
 */
export function WorkspaceHeader({
  parent = "CareerCrew",
  title,
  subtitle,
  actions,
  className,
}: {
  parent?: string
  title: string
  subtitle?: string
  actions?: ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        "flex h-[50px] shrink-0 items-center justify-between gap-3 border-b border-[var(--border-soft)] pl-[18px] pr-[14px]",
        className
      )}
    >
      <div className="flex min-w-0 items-baseline gap-1.5">
        <span className="text-[13px] text-ink-faint">{parent}</span>
        <span className="text-[13px] text-ink-faint opacity-70">/</span>
        <span className="text-[13px] font-medium text-ink">{title}</span>
        {subtitle && (
          <span className="ml-1.5 hidden truncate text-[11px] text-ink-faint lg:inline">{subtitle}</span>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </header>
  )
}
