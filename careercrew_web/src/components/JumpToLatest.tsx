import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

/** 用户离开底部时悬浮在右下角的"回到最新"按钮：小胶囊、弱边框、无彩色。 */
export function JumpToLatest({ visible, onClick, className }: { visible: boolean; onClick: () => void; className?: string }) {
  if (!visible) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "stream-fade-in absolute bottom-4 right-6 z-10 flex items-center gap-1 rounded-full border border-[var(--border-soft)] bg-workspace px-2.5 py-1 text-[11.5px] font-medium text-ink-soft shadow-popover transition-colors duration-100 hover:text-ink",
        className
      )}
    >
      <ChevronDown className="h-3.5 w-3.5" />
      回到最新
    </button>
  )
}
