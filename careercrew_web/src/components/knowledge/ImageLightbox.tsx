import { useEffect, useRef, useState, type MouseEvent } from "react"
import { X } from "lucide-react"
import { Tooltip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/** 知识库图片大图预览：滚轮缩放 + 拖拽平移 + Esc 关闭。 */
export function ImageLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const imgRef = useRef<HTMLImageElement>(null)
  const dragRef = useRef<{
    startX: number
    startY: number
    origX: number
    origY: number
    lastX: number
    lastY: number
  } | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    // 锁定 body 滚动：避免底层页面滚动条透过半透明遮罩显示成白线
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [onClose])

  // 滚轮缩放：用原生非 passive 监听，阻止背景滚动
  useEffect(() => {
    const el = imgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      // 归一化 delta：鼠标一格≈100px（deltaMode 1=行、2=页）
      let dy = e.deltaY
      if (e.deltaMode === 1) dy *= 16
      else if (e.deltaMode === 2) dy *= 100
      // 单次事件最多变化 0.5x~2x，避免"滚一下就最大"
      const ratio = Math.min(2, Math.max(0.5, Math.exp(-dy * 0.0015)))
      setView((v) => {
        const next = Math.min(5, Math.max(1, v.scale * ratio))
        const r = next / v.scale
        const max = (next - 1) * 500
        return {
          scale: next,
          x: Math.min(max, Math.max(-max, v.x * r)),
          y: Math.min(max, Math.max(-max, v.y * r)),
        }
      })
    }
    el.addEventListener("wheel", onWheel, { passive: false })
    return () => el.removeEventListener("wheel", onWheel)
  }, [])

  const resetZoom = () => setView({ scale: 1, x: 0, y: 0 })
  const maxOffset = (view.scale - 1) * 500
  const clampAxis = (v: number, max: number) => Math.min(max, Math.max(-max, v))

  /** 拖拽期间直接改 DOM transform（不触发 React 重渲染，避免滞后）。 */
  const applyTransform = (x: number, y: number, s: number) => {
    const el = imgRef.current
    if (el) el.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${s})`
  }

  const onMouseDown = (e: MouseEvent) => {
    if (view.scale <= 1) return
    e.preventDefault()
    dragRef.current = {
      startX: e.clientX, startY: e.clientY,
      origX: view.x, origY: view.y,
      lastX: view.x, lastY: view.y,
    }
  }

  const onMouseMove = (e: MouseEvent) => {
    const d = dragRef.current
    if (!d) return
    d.lastX = clampAxis(d.origX + (e.clientX - d.startX), maxOffset)
    d.lastY = clampAxis(d.origY + (e.clientY - d.startY), maxOffset)
    applyTransform(d.lastX, d.lastY, view.scale)
  }

  const endDrag = () => {
    const d = dragRef.current
    if (d) {
      // 松手时把最终位置同步回 state（只重渲染一次）
      setView((v) => ({ ...v, x: d.lastX, y: d.lastY }))
    }
    dragRef.current = null
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden bg-black/85 p-6"
      onClick={onClose}
    >
      <Tooltip label="关闭">
        <button
          className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition-colors duration-100 hover:bg-white/20"
          onClick={onClose}
          aria-label="关闭"
        >
          <X className="h-5 w-5" />
        </button>
      </Tooltip>
      <img
        ref={imgRef}
        src={src}
        alt="知识库图片大图"
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        className={cn(
          "max-h-[90vh] max-w-[90vw] object-contain select-none will-change-transform",
          view.scale > 1 ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"
        )}
        style={{ transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})` }}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
      />
      <div
        className="absolute bottom-5 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-xs text-white"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="tabular-nums">缩放 {Math.round(view.scale * 100)}%</span>
        {view.scale > 1 && <span className="text-white/60">拖拽可移动</span>}
        <button
          className="rounded-[5px] bg-white/15 px-2 py-0.5 transition-colors duration-100 hover:bg-white/25"
          onClick={resetZoom}
        >
          重置
        </button>
      </div>
    </div>
  )
}
