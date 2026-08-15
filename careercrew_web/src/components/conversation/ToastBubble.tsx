/** 页面级反馈 toast 气泡（悬浮于 Composer 上方居中）。 */
export function ToastBubble({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="absolute bottom-[130px] left-1/2 z-30 -translate-x-1/2 rounded-full border border-[var(--border-soft)] bg-workspace px-3 py-1.5 text-[12px] text-ink shadow-popover">
      {message}
    </div>
  )
}
