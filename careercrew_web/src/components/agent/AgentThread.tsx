import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * 对话消息基础组件（共享于会诊/面试/知识库/匹配/简历等页面）：
 * 用户消息右对齐弱灰气泡；助手消息左对齐、透明背景（内容阅读体验）。
 * 主聊天页使用 components/conversation/ 下的完整套件（含 Rail / 反馈 / 操作栏）。
 */

/** 用户消息：右对齐气泡，轻微不对称圆角（右下 5px）。 */
export function UserMessage({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("stream-fade-in flex justify-end", className)}>
      <div className="max-w-[68%] max-md:max-w-[84%] whitespace-pre-wrap rounded-[14px_14px_5px_14px] bg-[var(--user-bubble)] px-3.5 py-2.5 text-[14px] leading-[1.55] text-ink">
        {content}
      </div>
    </div>
  )
}

/** 助手消息：身份标签（代理色圆点 + 名称 + 工作状态）+ 正文。 */
export function AgentMessage({
  label,
  color,
  working = false,
  workingText = "正在生成回答…",
  className,
  children,
}: {
  label: string
  color?: string
  working?: boolean
  workingText?: string
  className?: string
  children?: ReactNode
}) {
  return (
    <div className={cn("stream-fade-in", className)}>
      <div className="mb-1.5 flex items-center gap-1.5">
        {color && (
          <span className="h-[6px] w-[6px] shrink-0 rounded-full" style={{ backgroundColor: color }} />
        )}
        <span className="text-[11.5px] font-[520] text-ink-faint">{label}</span>
        {working && (
          <span className="flex items-center gap-1.5 text-[11px] text-ink-faint">
            <span className="working-pulse h-1 w-1 rounded-full bg-current" />
            {workingText}
          </span>
        )}
      </div>
      <div className="text-[14px] leading-[1.6] text-ink">{children}</div>
    </div>
  )
}

/** 面板块（总调度官结论等强调性产物）：surface 圆角块，无强边框。 */
export function AgentPanel({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <div
      className={cn(
        "stream-fade-in rounded-[10px] border border-[var(--border-soft)] bg-surface-1 px-4 py-3.5",
        className
      )}
    >
      {children}
    </div>
  )
}
