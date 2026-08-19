import { useEffect, useRef, useState } from "react"
import { CircleAlert, Info } from "lucide-react"
import { subscribeToasts, type ToastNotice } from "@/lib/toastBus"

/**
 * 全局 toast 宿主：订阅 toastBus 的通知，顶部居中逐条展示，4 秒后自动消失。
 * 挂在 App 根部，所有页面/面板的静默失败点都能通过 notifyError() 提示用户。
 */
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
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.kind === "error" ? "alert" : "status"}
          className={
            t.kind === "error"
              ? "flex max-w-[480px] items-center gap-2 rounded-[8px] border border-destructive/40 bg-[#fdecea] px-3.5 py-2 text-[13px] text-[#b3261e] shadow-popover stream-fade-in"
              : "flex max-w-[480px] items-center gap-2 rounded-[8px] border border-[var(--border-soft)] bg-workspace px-3.5 py-2 text-[13px] text-ink shadow-popover stream-fade-in"
          }
        >
          {t.kind === "error" ? (
            <CircleAlert className="h-4 w-4 shrink-0" strokeWidth={1.8} />
          ) : (
            <Info className="h-4 w-4 shrink-0" strokeWidth={1.8} />
          )}
          <span className="min-w-0">{t.text}</span>
        </div>
      ))}
    </div>
  )
}
