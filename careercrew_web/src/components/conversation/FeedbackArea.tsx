import { useState } from "react"
import { MessageActions } from "@/components/conversation/MessageActions"
import { FeedbackPopover } from "@/components/conversation/FeedbackPopover"
import type { MessageFeedback } from "@/types"

/**
 * Agent 回答反馈区：操作栏（Copy / 👍 / 👎 / ↻ / ⋯）+ 点踩 Popover，
 * 反馈状态按 messageId 自管理。普通回答用 AssistantMessage 即可；
 * 自定义渲染的回答（如会诊总调度官结论）单独挂本组件即可获得一致的反馈闭环。
 */
export function FeedbackArea({
  messageId,
  content,
  onRegenerate,
  onFeedback,
}: {
  messageId: string
  content: string
  onRegenerate?: () => void
  onFeedback?: (fb: MessageFeedback) => void
}) {
  const [feedback, setFeedback] = useState<MessageFeedback | null>(null)
  const [dislikeOpen, setDislikeOpen] = useState(false)

  const toggleLike = () => {
    if (feedback?.rating === "positive") {
      setFeedback(null)
      return
    }
    const fb: MessageFeedback = { messageId, rating: "positive" }
    setFeedback(fb)
    onFeedback?.(fb)
  }

  const toggleDislike = () => {
    if (feedback?.rating === "negative") {
      setFeedback(null)
      setDislikeOpen(false)
      return
    }
    setDislikeOpen(true)
  }

  const submitDislike = (reason: NonNullable<MessageFeedback["reason"]>, comment: string) => {
    const fb: MessageFeedback = { messageId, rating: "negative", reason, comment: comment || undefined }
    setFeedback(fb)
    setDislikeOpen(false)
    onFeedback?.(fb)
  }

  return (
    <div className="relative">
      <MessageActions
        content={content}
        feedback={feedback}
        onCopy={() => {}}
        onToggleLike={toggleLike}
        onToggleDislike={toggleDislike}
        onRegenerate={onRegenerate}
      />
      <FeedbackPopover open={dislikeOpen} onClose={() => setDislikeOpen(false)} onSubmit={submitDislike} />
    </div>
  )
}
