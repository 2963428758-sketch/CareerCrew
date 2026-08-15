import type { ReactNode } from "react"
import { turnAnchorId } from "@/components/conversation/turn"
import { UserMessage } from "@/components/conversation/UserMessage"

/**
 * 一轮对话的外壳：anchor id（Rail 点击滚动目标）+ 用户气泡 + 助手区域。
 * isUser=false 时（历史孤儿 assistant 消息）只渲染助手区域，不显示气泡。
 */
export function TurnSection({
  turnId,
  userContent,
  isUser,
  highlighted,
  onEdit,
  children,
}: {
  turnId: string
  userContent: string
  isUser: boolean
  highlighted?: boolean
  onEdit?: (text: string) => void
  children?: ReactNode
}) {
  return (
    <section id={turnAnchorId(turnId)} className="relative scroll-mt-24">
      {isUser && (
        <UserMessage
          content={userContent}
          turnId={turnId}
          highlighted={highlighted}
          onEdit={onEdit}
        />
      )}
      {children && <div className="mt-4">{children}</div>}
    </section>
  )
}
