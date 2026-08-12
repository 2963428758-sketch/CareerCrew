import { ChevronDown } from "lucide-react"

/** 用户离开底部时悬浮在右下角的"回到最新"按钮 */
export function JumpToLatest({ visible, onClick }: { visible: boolean; onClick: () => void }) {
  if (!visible) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className="stream-fade-in absolute bottom-4 right-6 z-10 flex items-center gap-1 rounded-full border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground shadow-md transition-colors hover:text-foreground"
      title="回到最新"
    >
      <ChevronDown className="h-3.5 w-3.5" />
      回到最新
    </button>
  )
}
