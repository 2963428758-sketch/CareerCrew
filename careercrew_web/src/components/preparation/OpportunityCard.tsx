import { ExternalLink } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { isSafeHttpUrl } from "@/lib/preparation"
import type { Opportunity } from "@/lib/preparation"
import { cn } from "@/lib/utils"

/** 岗位卡片：列表选择 + 详情摘要（编辑/删除动作由父层提供）。 */
export function OpportunityCard({
  item,
  selected,
  onSelect,
  onEdit,
  onDelete,
}: {
  item: Opportunity
  selected: boolean
  onSelect: () => void
  onEdit?: () => void
  onDelete?: () => void
}) {
  const safeUrl = isSafeHttpUrl(item.url)
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onSelect()
        }
      }}
      className={cn(
        "cursor-pointer rounded-[10px] border border-[var(--border-soft)] bg-card p-3 text-[13px] transition-colors hover:border-ink-faint/60",
        selected && "border-ink/50 bg-surface-2",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-[560] text-ink">
          {item.company} · {item.title}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {onEdit && (
            <Button
              variant="ghost"
              size="sm"
              className="h-[24px] px-2 text-[11.5px]"
              onClick={(e) => {
                e.stopPropagation()
                onEdit()
              }}
            >
              编辑
            </Button>
          )}
          {onDelete && (
            <Button
              variant="ghost"
              size="sm"
              className="h-[24px] px-2 text-[11.5px] text-destructive hover:text-destructive"
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
            >
              删除
            </Button>
          )}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-faint">
        {item.city && <Badge variant="secondary" className="text-[10.5px]">{item.city}</Badge>}
        {item.salary && <Badge variant="secondary" className="text-[10.5px]">{item.salary}</Badge>}
        {item.source && <Badge variant="outline" className="text-[10.5px]">{item.source}</Badge>}
        {safeUrl && (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="inline-flex items-center gap-0.5 hover:text-ink"
            onClick={(e) => e.stopPropagation()}
          >
            链接 <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      <p className="mt-1.5 line-clamp-2 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-ink-soft">
        {item.jd || "（暂无 JD）"}
      </p>
    </div>
  )
}
