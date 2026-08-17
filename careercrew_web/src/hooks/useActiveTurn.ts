import { useCallback, useEffect, useRef, useState, type RefObject } from "react"

/**
 * 当前 Turn 检测（IntersectionObserver，不监听 scroll 做高频计算）。
 *
 * 观察每个用户气泡（[data-turn-anchor]）。在 IO 回调（只在参考线带穿越时触发）里
 * 一次性重读全部元素 rect，选「top 最接近且不超过视口上方参考线」的 Turn；
 * 若全部都在参考线之下（刚滚回顶部），退回第一个 Turn。
 *
 * select()：Rail 横条点击等手动选择。选中后立即激活，并在滚动动画期间挂起
 * IO 重算；滚动静止 180ms 后（或最多 2.5s）校验一次：被点击的轮次仍在视口内
 * 就保持用户选择（短对话无滚动时点击依然生效），已滚出视口才交还几何规则。
 */
export function useActiveTurn(ids: string[], scrollRef: RefObject<HTMLElement | null>) {
  const [activeId, setActiveIdState] = useState<string | null>(null)
  const activeRef = useRef<string | null>(null)
  const recomputeRef = useRef<((force?: boolean) => void) | null>(null)
  const clickedRef = useRef<string | null>(null)
  const settleRef = useRef<{
    timer: ReturnType<typeof setTimeout> | null
    deadline: number
    removeScroll: (() => void) | null
    pending: boolean
  }>({ timer: null, deadline: 0, removeScroll: null, pending: false })

  const setActive = useCallback((id: string | null) => {
    if (id !== activeRef.current) {
      activeRef.current = id
      setActiveIdState(id)
    }
  }, [])

  /** 手动选中：立即激活；滚动静止后校验点击目标是否仍在视口内 */
  const select = useCallback(
    (id: string) => {
      setActive(id)
      clickedRef.current = id
      const s = settleRef.current
      if (s.timer) clearTimeout(s.timer)
      if (s.removeScroll) {
        s.removeScroll()
        s.removeScroll = null
      }
      s.pending = true
      s.deadline = Date.now() + 2500

      const finish = () => {
        if (s.timer) {
          clearTimeout(s.timer)
          s.timer = null
        }
        if (s.removeScroll) {
          s.removeScroll()
          s.removeScroll = null
        }
        s.pending = false
        const clicked = clickedRef.current
        clickedRef.current = null
        const root = scrollRef.current
        const el = clicked && root ? root.querySelector<HTMLElement>(`[data-turn-anchor="${clicked}"]`) : null
        if (el) {
          const r = el.getBoundingClientRect()
          const rr = root!.getBoundingClientRect()
          // 被点击的轮次仍可见（哪怕没发生任何滚动）：保持用户选择
          const visible = r.bottom > rr.top + 32 && r.top < rr.bottom - 32
          if (visible) return
        }
        // 点击目标已滚出视口：交还给几何规则
        recomputeRef.current?.(true)
      }

      // 滚动事件只重置定时器（不读布局），静止 180ms 后认为动画结束
      const arm = () => {
        if (s.timer) clearTimeout(s.timer)
        const remaining = s.deadline - Date.now()
        s.timer = setTimeout(finish, Math.min(remaining, 180))
      }

      const root = scrollRef.current
      if (root) {
        root.addEventListener("scroll", arm, { passive: true })
        s.removeScroll = () => root.removeEventListener("scroll", arm)
      }
      arm()
    },
    [scrollRef, setActive]
  )

  useEffect(() => {
    const root = scrollRef.current
    const s = settleRef.current // 稳定对象引用（内容原地更新），清理时读到的仍是同一份状态
    if (!root || typeof IntersectionObserver === "undefined") {
      // jsdom / 老环境兜底：默认最后一个 Turn
      setActive(ids.length ? ids[ids.length - 1] : null)
      return
    }

    const els = () =>
      Array.from(root.querySelectorAll<HTMLElement>("[data-turn-anchor]")).filter((el) =>
        ids.includes(el.dataset.turnAnchor ?? "")
      )

    const recompute = (force = false) => {
      if (!force && settleRef.current.pending) return
      const list = els()
      if (!list.length) {
        setActive(null)
        return
      }
      const lineTop = root.getBoundingClientRect().top + 108
      let above: { id: string; top: number } | null = null
      let first: { id: string; top: number } | null = null
      for (const el of list) {
        const top = el.getBoundingClientRect().top
        if (!first || top < first.top) first = { id: el.dataset.turnAnchor!, top }
        if (top <= lineTop && (!above || top > above.top)) above = { id: el.dataset.turnAnchor!, top }
      }
      setActive((above ?? first)?.id ?? null)
    }
    recomputeRef.current = recompute

    // 参考线带：108px ~ 视口 60%。只有在这条带上穿越时才触发回调（低成本），
    // 回调内重读全部 rect 保证激活态精确到最近一次穿越。
    const observer = new IntersectionObserver(
      () => recompute(),
      { root, rootMargin: "-108px 0px -40% 0px", threshold: [0, 0.01] }
    )

    // 消息集变化（新 Turn / 加载历史）时强制重算一次，不受挂起影响
    recompute(true)
    for (const el of els()) observer.observe(el)

    return () => {
      observer.disconnect()
      recomputeRef.current = null
      if (s.timer) clearTimeout(s.timer)
      if (s.removeScroll) s.removeScroll()
      s.pending = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ids.join 作为稳定依赖，root 挂载后不再变化
  }, [ids.join("|"), scrollRef, setActive])

  return { activeId, select }
}
