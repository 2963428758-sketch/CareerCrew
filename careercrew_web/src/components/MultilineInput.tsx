import { useRef, useEffect, type KeyboardEvent } from "react"
import { cn } from "@/lib/utils"

interface MultilineInputProps {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  placeholder?: string
  disabled?: boolean
  className?: string
}

/**
 * 多行输入框：auto-grow textarea（独立使用时为极简无边框样式）。
 * - Enter 发送 / Shift + Enter 换行
 * - 多行粘贴原样保留（核心痛点：CLI input() 只取一行）
 * 聊天页统一使用 PromptComposer；本组件保留给其他内嵌场景。
 */
export function MultilineInput({
  value,
  onChange,
  onSend,
  placeholder = "输入消息…（Enter 发送，Shift + Enter 换行）",
  disabled,
  className,
}: MultilineInputProps) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // auto-grow：空值时保持 CSS 最小高度（长占位符换行会把 scrollHeight 撑高，不能算进去）
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (!el.value) {
      el.style.height = ""
      return
    }
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 240) + "px"
  }, [value])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (!disabled && value.trim()) onSend()
    }
  }

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      placeholder={placeholder}
      disabled={disabled}
      rows={1}
      className={cn(
        "block w-full resize-none rounded-[7px] border border-input bg-card px-2.5 py-2 text-[14px] leading-[1.5] outline-none",
        "placeholder:text-ink-faint focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-50",
        "min-h-[40px] max-h-[240px]",
        className
      )}
    />
  )
}
