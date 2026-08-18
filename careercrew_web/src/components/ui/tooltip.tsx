import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { cn } from "@/lib/utils"

type TooltipPlace = "top" | "bottom" | "left" | "right"

const EDGE_BAND = 150 // 距屏幕左右边缘多近时改用侧贴定位

/**
 * 自定义方形气泡 Tooltip（全站统一，替代浏览器原生 title）：
 * - 悬停 150ms 后显示，fixed 定位（不受 overflow-hidden 裁剪）
 * - 位置自适应：
 *   · 触发元素在屏幕左边缘（如折叠侧边栏图标）→ 气泡贴到元素右侧、垂直居中
 *   · 在右边缘（如右上角图标）→ 贴到元素左侧
 *   · 其余 → 上方居中显示，上方空间不足自动翻到下方
 * - 始终夹在视口内，不会溢出屏幕
 * - 移出、点击、页面滚动时自动隐藏
 * 包裹层使用 display:contents，不改变原布局（flex 布局安全）。
 */
export function Tooltip({
  label,
  side = "auto",
  className,
  children,
}: {
  /** 为空时不渲染提示（也不挂 hover 监听），仅原样渲染子元素 */
  label?: string | null
  side?: "top" | "bottom" | "auto"
  className?: string
  children: ReactNode
}) {
  const [pos, setPos] = useState<{ x: number; y: number; tx: string; ty: string } | null>(null)
  const wrapRef = useRef<HTMLSpanElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setPos(null)
  }, [])

  const show = useCallback(() => {
    if (!label) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      const child = wrapRef.current?.firstElementChild as HTMLElement | null
      if (!child) return
      const r = child.getBoundingClientRect()
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      const margin = 8

      // 显式方向优先；否则按边缘自适应：左边缘→右侧，右边缘→左侧，中间→上/下（空间不足自动翻转）
      let place: TooltipPlace
      if (side !== "auto") place = side
      else if (cx < EDGE_BAND) place = "right"
      else if (window.innerWidth - cx < EDGE_BAND) place = "left"
      else place = r.top > 96 ? "top" : "bottom"

      let x: number
      let y: number
      let tx: string
      let ty: string
      if (place === "right") {
        x = Math.min(r.right + 8, window.innerWidth - margin)
        y = Math.min(Math.max(cy, margin + 24), window.innerHeight - margin - 24)
        tx = "0"
        ty = "-50%"
      } else if (place === "left") {
        x = Math.max(r.left - 8, margin)
        y = Math.min(Math.max(cy, margin + 24), window.innerHeight - margin - 24)
        tx = "-100%"
        ty = "-50%"
      } else {
        // 上/下：优先水平居中；贴近右边缘时改为右对齐，避免溢出屏幕
        if (place === "top") {
          y = r.top - 6
          ty = "-100%"
        } else {
          y = r.bottom + 6
          ty = "0"
        }
        if (cx + 140 <= window.innerWidth - margin) {
          x = cx
          tx = "-50%"
        } else {
          x = Math.min(r.right - 8, window.innerWidth - margin)
          tx = "-100%"
        }
      }
      setPos({ x, y, tx, ty })
    }, 150)
  }, [side, label])

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  // 任意滚动（含对话区内部滚动）时隐藏，避免提示停留在错误位置
  useEffect(() => {
    if (!pos) return
    const onScroll = () => hide()
    window.addEventListener("scroll", onScroll, { capture: true, passive: true })
    return () => window.removeEventListener("scroll", onScroll, { capture: true })
  }, [pos, hide])

  if (!label) return <>{children}</>
  return (
    <span
      ref={wrapRef}
      onMouseEnter={show}
      onMouseLeave={hide}
      onPointerDown={hide}
      onClick={hide}
      className={cn("contents", className)}
    >
      {children}
      {pos && (
        <span
          role="tooltip"
          className="pointer-events-none fixed z-[70] w-max max-w-[280px] rounded-[7px] border border-[var(--border-soft)] bg-workspace px-2.5 py-1.5 text-center text-[12px] leading-[1.4] text-ink shadow-popover"
          style={{
            left: pos.x,
            top: pos.y,
            transform: `translate(${pos.tx}, ${pos.ty})`,
          }}
        >
          {label}
        </span>
      )}
    </span>
  )
}
