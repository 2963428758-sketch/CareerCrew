import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * 空状态（Codex 风格）：克制——20px / weight 560 标题 + 13px 淡墨说明，
 * 不放大图标、不做渐变。操作引导交给下方 Prompt Composer。
 */
export function EmptyState({
  title,
  description,
  accent,
  children,
  className,
}: {
  title: string
  description?: ReactNode
  accent?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("mx-auto mb-10 mt-14 max-w-[520px] text-center", className)}>
      {accent && <div className="mb-5 flex justify-center">{accent}</div>}
      <h2 className="text-[20px] font-[560] leading-[1.3] tracking-[-0.015em] text-ink">{title}</h2>
      {description && <div className="mt-2 text-[13px] leading-[1.5] text-ink-soft">{description}</div>}
      {children}
    </div>
  )
}

/** Agent 身份色点行（空状态装饰，低存在感）。 */
export function AgentDots({ colors }: { colors: string[] }) {
  return (
    <div className="flex items-center gap-1.5">
      {colors.map((c) => (
        <span key={c} className="h-2 w-2 rounded-full opacity-80" style={{ backgroundColor: c }} />
      ))}
    </div>
  )
}
