import { useCallback, useEffect, useRef, useState } from "react"

/** 距离底部多少像素内视为"在底部"，避免轻微滚动就恢复跟随 */
const NEAR_BOTTOM_PX = 80

/**
 * 智能跟随滚动：内容变化（流式文本/消息）时仅当用户本就位于底部才自动滚到底；
 * 用户上滑后停止强制滚动，滚回底部自动恢复；jumpToLatest() 可一键回底。
 */
export function useChatScroll(followDeps: unknown[]) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const atBottomRef = useRef(true)
  const [isAtBottom, setIsAtBottom] = useState(true)

  const update = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
    if (nearBottom !== atBottomRef.current) {
      atBottomRef.current = nearBottom
      setIsAtBottom(nearBottom)
    }
  }, [])

  // 监听滚动：只在"在底部/离开底部"状态翻转时 setState，避免高频重渲染
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    update()
    el.addEventListener("scroll", update, { passive: true })
    return () => el.removeEventListener("scroll", update)
  }, [update])

  // 内容变化时跟随：每次先实测当前滚动位置（不依赖 scroll 事件时序），
  // 仅在用户位于底部附近时才滚动，避免程序化上滑后仍被拉回
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    update()
    if (!atBottomRef.current) return
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps 由调用方按流式内容传入
  }, followDeps)

  const jumpToLatest = useCallback(() => {
    atBottomRef.current = true
    setIsAtBottom(true)
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [])

  return { scrollRef, isAtBottom, showJumpToLatest: !isAtBottom, jumpToLatest }
}
