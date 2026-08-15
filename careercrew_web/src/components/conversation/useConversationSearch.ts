import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react"
import type { RefObject } from "react"
import { buildSearchIndex, findMatches, stepMatch } from "@/lib/conversationSearch"
import { clearHighlight, highlightNthOccurrence } from "@/components/conversation/searchHighlight"

/** 供 useConversationSearch 消费的消息最小 shape（user/assistant + 正文）。 */
export interface SearchMessage {
  id: string
  role: "user" | "assistant"
  content?: string
  turnId?: string
}

/**
 * 当前会话搜索（§11）：内存索引 + 大小写不敏感匹配 + 前/后循环跳转 +
 * 仅 Workspace 聚焦/悬停时拦截 Ctrl/Cmd+F + 当前匹配低饱和高亮 + 平滑滚动定位。
 */
export function useConversationSearch(
  messages: SearchMessage[],
  scrollRef: RefObject<HTMLElement | null>,
  workspaceRef: RefObject<HTMLElement | null>
) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [currentIndex, setCurrentIndex] = useState(0)
  const [workspaceHovered, setWorkspaceHovered] = useState(false)

  // 内存索引 + 匹配集（随 messages / keyword 变化）
  const index = useMemo(() => buildSearchIndex(messages), [messages])
  const matches = useMemo(() => findMatches(index, keyword), [index, keyword])

  // keyword 变化时重置到第一项
  useEffect(() => setCurrentIndex(0), [keyword, messages])

  const total = matches.length
  const hasResults = total > 0

  /** 打开搜索条（由 header 搜索图标 / Ctrl+F 触发）。 */
  const openSearch = useCallback(() => setOpen(true), [])
  const close = useCallback(() => {
    setOpen(false)
    setKeyword("")
    setCurrentIndex(0)
  }, [])

  // currentIndex 变化 → 高亮 + 滚动（首次打开、next/prev）
  useEffect(() => {
    if (!open) return
    const root = scrollRef.current
    if (!root) return
    if (currentIndex < 0 || currentIndex >= matches.length) {
      clearHighlight(root)
      return
    }
    const el = highlightNthOccurrence(root, keyword, currentIndex)
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [open, currentIndex, keyword, matches, scrollRef])

  // 关闭/无结果时清除高亮
  useEffect(() => {
    if (open && hasResults) return
    const root = scrollRef.current
    if (root) clearHighlight(root)
  }, [open, hasResults, scrollRef])

  // 卸载时清理
  useEffect(() => {
    const root = scrollRef.current
    return () => {
      if (root) clearHighlight(root)
    }
  }, [scrollRef])

  const next = useCallback(() => {
    setCurrentIndex((i) => stepMatch(matches, i, 1))
  }, [matches])

  const prev = useCallback(() => {
    setCurrentIndex((i) => stepMatch(matches, i, -1))
  }, [matches])

  /** Ctrl/Cmd+F：仅 Workspace 聚焦或悬停时拦截（§11.3）。 */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "f" || e.key === "F")) {
        const workspace = workspaceRef.current
        const activeEl = document.activeElement
        if (
          (workspace && activeEl && workspace.contains(activeEl as Node)) ||
          workspaceHovered
        ) {
          e.preventDefault()
          openSearch()
        }
      }
      if (e.key === "Escape" && open) {
        e.preventDefault()
        close()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [workspaceRef, workspaceHovered, open, openSearch, close])

  const onMouseEnter = useCallback(() => setWorkspaceHovered(true), [])
  const onMouseLeave = useCallback(() => setWorkspaceHovered(false), [])

  return {
    open,
    openSearch,
    close,
    keyword,
    setKeyword,
    currentIndex,
    total,
    hasResults,
    next,
    prev,
    workspaceHoverHandlers: { onMouseEnter, onMouseLeave },
  }
}
