import { useCallback, useEffect, useRef, useState, type RefObject } from "react"
import { useActiveTurn } from "@/hooks/useActiveTurn"
import { turnAnchorId } from "@/components/conversation/turn"

/**
 * 对话页导航套装：当前 Turn 检测 + Rail 点击跳转（平滑滚动 + 气泡 900ms 高亮）。
 */
export function useConversationNavigation(turnIds: string[], scrollRef: RefObject<HTMLElement | null>) {
  const { activeId, select } = useActiveTurn(turnIds, scrollRef)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const selectTurn = useCallback(
    (turnId: string) => {
      select(turnId)
      const el = document.getElementById(turnAnchorId(turnId))
      if (el && typeof el.scrollIntoView === "function") {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
      setHighlightId(turnId)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setHighlightId(null), 900)
    },
    [select]
  )

  return { activeId, selectTurn, highlightId }
}
