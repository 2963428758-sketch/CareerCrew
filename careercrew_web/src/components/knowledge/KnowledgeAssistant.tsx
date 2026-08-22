import { type ReactNode } from "react"
import { ThinkingPulse } from "@/components/ThinkingIndicator"
import { MarkdownContent } from "@/components/MarkdownContent"
import { AssistantMessage } from "@/components/conversation/AssistantMessage"
import { AGENT_META, type MessageFeedback } from "@/types"
import { cn } from "@/lib/utils"
import { imagePathsIn, renderKnowledgeText, useAuthenticatedImages } from "./useAuthenticatedImages"
import { SourceList } from "./KnowledgeSources"
import type { KnowledgeMessage } from "./types"

export function KnowledgeAssistant({ msg, threadId, isStreaming, streamingText, thinking, initializing, onPreview, versionSwitcher, onRegenerate, onFeedback }: {
  msg: KnowledgeMessage
  threadId: string
  isStreaming: boolean
  streamingText: string
  thinking: boolean
  initializing: boolean
  onPreview: (url: string) => void
  versionSwitcher?: ReactNode
  onRegenerate?: () => void
  onFeedback?: (fb: MessageFeedback) => void
}) {
  const meta = AGENT_META.knowledge_advisor
  const content = isStreaming ? streamingText : msg.content
  const images = useAuthenticatedImages(isStreaming ? imagePathsIn(streamingText) : imagePathsIn(msg.content))
  const rendered = renderKnowledgeText(content, images)

  return (
    <AssistantMessage
      messageId={msg.id}
      stableMessageId={msg.messageId}
      threadId={threadId}
      content={content}
      label={meta.label}
      color={meta.color}
      streaming={isStreaming}
      completed={!isStreaming}
      thinking={thinking}
      initializing={isStreaming && !content && initializing}
      initText="正在检索知识库"
      workingText="正在检索知识库…"
      versionSwitcher={versionSwitcher}
      contentNode={
        <>
          <MarkdownContent className={cn(isStreaming && content && !thinking && "typing-cursor")}>
            {rendered}
          </MarkdownContent>
          {isStreaming && content && thinking && <ThinkingPulse />}
        </>
      }
      onRegenerate={onRegenerate}
      onFeedback={onFeedback}
    >
      {!isStreaming && msg.sources && msg.sources.length > 0 && (
        <SourceList sources={msg.sources} onPreview={onPreview} />
      )}
    </AssistantMessage>
  )
}

export function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors duration-100",
        active
          ? "border-transparent bg-button-ink text-button-onink"
          : "border-[var(--border-soft)] bg-transparent text-ink-soft hover:bg-[var(--hover)] hover:text-ink"
      )}
    >
      {children}
    </button>
  )
}
