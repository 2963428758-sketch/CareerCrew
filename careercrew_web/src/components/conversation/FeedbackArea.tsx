import { useEffect, useRef, useState } from "react"
import { MessageActions } from "@/components/conversation/MessageActions"
import { FeedbackPopover } from "@/components/conversation/FeedbackPopover"
import { deleteMessageFeedback, putMessageFeedback, type FeedbackRequest } from "@/lib/feedback"
import { hydrateThreadFeedback, removePersistedFeedback, setPersistedFeedback, usePersistedFeedback } from "@/lib/feedbackState"
import { notifyError } from "@/lib/toastBus"
import type { MessageFeedback } from "@/types"

/**
 * Agent 回答反馈区：操作栏（Copy / 👍 / 👎 / ↻ / ⋯）+ 点踩 Popover，
 * 反馈状态按 messageId 自管理。普通回答用 AssistantMessage 即可；
 * 自定义渲染的回答（如会诊总调度官结论）单独挂本组件即可获得一致的反馈闭环。
 */
export function FeedbackArea({
  messageId,
  threadId,
  content,
  completed = true,
  onRegenerate,
  onFeedback,
}: {
  /** 后端稳定 message_id；缺失时仅保留复制/重新生成，不允许反馈写入。 */
  messageId?: string
  threadId: string
  content: string
  /** 是否为已完成回答；false（streaming）时隐藏 👍/👎/↻（§17）。 */
  completed?: boolean
  onRegenerate?: () => void
  onFeedback?: (fb: MessageFeedback) => void
}) {
  if (!messageId) {
    return (
      <div className="relative">
        <MessageActions
          content={content}
          feedback={null}
          feedbackAvailable={false}
          completed={completed}
          onCopy={() => {}}
          onToggleLike={() => {}}
          onToggleDislike={() => {}}
          onRegenerate={onRegenerate}
        />
      </div>
    )
  }
  return (
    <PersistedFeedbackArea
      messageId={messageId}
      threadId={threadId}
      content={content}
      completed={completed}
      onRegenerate={onRegenerate}
      onFeedback={onFeedback}
    />
  )
}

function PersistedFeedbackArea({
  messageId,
  threadId,
  content,
  completed,
  onRegenerate,
  onFeedback,
}: {
  messageId: string
  threadId: string
  content: string
  completed: boolean
  onRegenerate?: () => void
  onFeedback?: (fb: MessageFeedback) => void
}) {
  const feedback = usePersistedFeedback(threadId, messageId)
  const [dislikeOpen, setDislikeOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const anchorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void hydrateThreadFeedback(threadId).catch(() => {
      // 预加载历史反馈失败（如未落库新会话返回 404）时静默忽略，不弹全局 toast 干扰正常使用
    })
  }, [threadId, messageId])

  const publish = (saved: NonNullable<typeof feedback>) => {
    onFeedback?.({
      messageId: saved.messageId,
      rating: saved.rating,
      reason: saved.reason,
      comment: saved.comment,
      shareContext: saved.shareContext,
    })
  }

  const revoke = async () => {
    if (pending) return
    setPending(true)
    try {
      await deleteMessageFeedback(messageId)
      removePersistedFeedback(threadId, messageId)
      setDislikeOpen(false)
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "撤销反馈失败，请重试")
    } finally {
      setPending(false)
    }
  }

  const save = async (request: FeedbackRequest) => {
    if (pending) return false
    setPending(true)
    try {
      const saved = await putMessageFeedback(messageId, request)
      setPersistedFeedback(threadId, saved)
      publish(saved)
      return true
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "保存反馈失败，请重试")
      return false
    } finally {
      setPending(false)
    }
  }

  const toggleLike = async () => {
    if (feedback?.rating === "positive") {
      await revoke()
      return
    }
    await save({ rating: "positive", shareContext: false })
  }

  const toggleDislike = async () => {
    if (feedback?.rating === "negative") {
      await revoke()
      return
    }
    setDislikeOpen(true)
  }

  const submitDislike = async (
    reason: NonNullable<MessageFeedback["reason"]>,
    comment: string,
    shareContext: boolean
  ) => {
    if (await save({ rating: "negative", reason, comment: comment || undefined, shareContext })) {
      setDislikeOpen(false)
    }
  }

  return (
    <div ref={anchorRef} className="relative">
      <MessageActions
        content={content}
        feedback={feedback}
        completed={completed}
        messageId={messageId}
        onCopy={() => {}}
        onToggleLike={toggleLike}
        onToggleDislike={toggleDislike}
        onRegenerate={onRegenerate}
        disabled={pending}
      />
      <FeedbackPopover
        open={dislikeOpen}
        pending={pending}
        anchorRef={anchorRef}
        onClose={() => setDislikeOpen(false)}
        onSubmit={submitDislike}
      />
    </div>
  )
}
