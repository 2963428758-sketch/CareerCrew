import { useEffect, useRef, useState } from "react"
import { CircleAlert, CheckCircle2, Info } from "lucide-react"
import { subscribeToasts, type ToastNotice } from "@/lib/toastBus"
import { cn } from "@/lib/utils"

/**
 * 全局 toast 宿主：订阅 toastBus 的通知，顶部居中逐条展示，4 秒后自动消失。
 * 挂在 App 根部，所有页面/面板的操作结果与静默失败点都经这里弹出。
 * 视觉：半透明毛玻璃卡片 + 类型色图标 + 左侧色条；入场自顶部滑入。
 */
const TOAST_STYLE: Record<ToastNotice["kind"], { icon: typeof Info; ring: string; bar: string; iconColor: string }> = {
  success: {
    icon: CheckCircle2,
    ring: "border-emerald-500/30",
    bar: "bg-emerald-500",
    iconColor: "text-emerald-600 dark:text-emerald-400",
  },
  error: {
    icon: CircleAlert,
    ring: "border-destructive/40",
    bar: "bg-destructive",
    iconColor: "text-destructive",
  },
  info: {
    icon: Info,
    ring: "border-[var(--border-soft)]",
    bar: "bg-primary",
    iconColor: "text-primary",
  },
}

export function ToastHost() {
  const [toasts, setToasts] = useState<ToastNotice[]>([])
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  useEffect(() => {
    const map = timers.current
    const unsubscribe = subscribeToasts((notice) => {
      setToasts((prev) => [...prev.slice(-2), notice])
      const timer = setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== notice.id))
        map.delete(notice.id)
      }, 4000)
      map.set(notice.id, timer)
    })
    return () => {
      unsubscribe()
      for (const timer of map.values()) clearTimeout(timer)
      map.clear()
    }
  }, [])

  if (toasts.length === 0) return null

  return (
    <div className="pointer-events-none fixed inset-x-0 top-5 z-[70] flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => {
        const style = TOAST_STYLE[t.kind]
        const Icon = style.icon
        return (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={cn(
              "toast-slide-in flex max-w-[520px] min-w-[240px] items-stretch overflow-hidden rounded-[10px] border bg-workspace/95 shadow-popover backdrop-blur-sm",
              style.ring
            )}
          >
            <div className={cn("w-[3px] shrink-0 rounded-full my-2 ml-2.5", style.bar)} aria-hidden />
            <div className="flex flex-1 items-center gap-2.5 px-3 py-2.5">
              <Icon className={cn("h-4 w-4 shrink-0", style.iconColor)} strokeWidth={1.8} />
              <span className="min-w-0 text-[13px] leading-[1.5] text-ink">{t.text}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
