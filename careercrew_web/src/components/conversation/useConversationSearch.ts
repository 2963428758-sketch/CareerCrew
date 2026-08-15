import {
  useCallback,
  useEffect,
  useState,
} from "react"
import type { RefObject } from "react"
import { stepMatch } from "@/lib/conversationSearch"
import {
  clearHighlight,
  findRenderedMatches,
  highlightNthOccurrence,
} from "@/components/conversation/searchHighlight"

/** 供 useConversationSearch 消费的消息最小 shape（user/assistant + 正文）。 */
export interface SearchMessage {
  id: string
  role: "user" | "assistant"
  content?: string
  turnId?: string
}

/**
 * 当前会话搜索（§11）：内存匹配 + 大小写不敏感 + 前/后循环跳转 +
 * 仅 Workspace 聚焦/悬停时拦截 Ctrl/Cmd+F（Esc 同样 scoped）+ 当前匹配低饱和
 * 高亮 + 平滑滚动定位。
 *
 * 计数与高亮共享同一文本域：`findRenderedMatches(scrollRef.current, keyword)`
 * 在“已渲染文本节点”上产出文档顺序的匹配列表（覆盖 markdown 富文本），
 * `total` 与高亮 ordinal 均来自该列表，保证二者永远一致。
 */
export function useConversationSearch(
  messages: SearchMessage[],
  scrollRef: RefObject<HTMLElement | null>,
  workspaceRef: RefObject<HTMLElement | null>
) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [currentIndex, setCurrentIndex] = useState(0)
  const [matches, setMatches] = useState(0)
  const [workspaceHovered, setWorkspaceHovered] = useState(false)

  // 在 open/keyword/messages/DOM 变化时，从“已渲染文本节点”重新计算匹配总数。
  // 与高亮器消费同一文本域（同一 findRenderedMatches），保证 counter 与 highlight 一致。
  useEffect(() => {
    if (!open) {
      setMatches(0)
      return
    }
    const root = scrollRef.current
    setMatches(root ? findRenderedMatches(root, keyword).length : 0)
  }, [open, keyword, messages, scrollRef])

  // keyword 变化时重置到第一项
  useEffect(() => setCurrentIndex(0), [keyword, messages])

  const total = matches
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
    if (currentIndex < 0 || currentIndex >= total) {
      clearHighlight(root)
      return
    }
    const el = highlightNthOccurrence(root, keyword, currentIndex)
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [open, currentIndex, keyword, total, scrollRef])

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
    setCurrentIndex((i) => stepMatch(total, i, 1))
  }, [total])

  const prev = useCallback(() => {
    setCurrentIndex((i) => stepMatch(total, i, -1))
  }, [total])

  /** Workspace 聚焦或悬停的 scope 谓词（Ctrl/Cmd+F 与 Esc 共用，§11.3）。 */
  const isWorkspaceScoped = useCallback((): boolean => {
    const workspace = workspaceRef.current
    const activeEl = document.activeElement
    return (
      (workspace != null && activeEl != null && workspace.contains(activeEl as Node)) ||
      workspaceHovered
    )
  }, [workspaceRef, workspaceHovered])

  /** Ctrl/Cmd+F 与 Esc 均仅 Workspace 聚焦/悬停时拦截（§11.3，scoped）。 */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "f" || e.key === "F")) {
        if (isWorkspaceScoped()) {
          e.preventDefault()
          openSearch()
        }
      }
      if (e.key === "Escape" && open && isWorkspaceScoped()) {
        e.preventDefault()
        close()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [isWorkspaceScoped, open, openSearch, close])

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
