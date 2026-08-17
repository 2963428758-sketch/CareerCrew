import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { MarkdownContent } from "@/components/MarkdownContent"
import { InitIndicator, ThinkingPulse } from "@/components/ThinkingIndicator"
import { FeedbackArea } from "@/components/conversation/FeedbackArea"
import { Sources } from "@/components/conversation/Sources"
import type { KnowledgeSource, MessageFeedback } from "@/types"

/**
 * Agent 回答（Codex 风格）：靠左、透明背景（长文阅读体验）、
 * 顶部小标签（色点 + 名称 + 工作状态）、底部操作栏 + 点踩反馈 Popover。
 * 各对话页可通过 contentNode 自定义正文渲染、children 插入附加内容
 * （如知识库来源列表、会诊调度面板）。
 */
export function AssistantMessage({
  messageId: _messageId,
  content,
  label,
  color,
  streaming = false,
  completed = true,
  stableMessageId,
  threadId,
  thinking = false,
  initializing = false,
  workingText = "正在生成回答…",
  initText = "规划师正在思考",
  sources,
  contentNode,
  children,
  versionSwitcher,
  onRegenerate,
  onFeedback,
  className,
}: {
  messageId: string
  content: string
  label?: string
  color?: string
  streaming?: boolean
  /** 是否已完成回答；false 时隐藏 👍/👎/↻（§17）。 */
  completed?: boolean
  /** 后端稳定 message_id：More 菜单「复制消息 ID」与 Feedback 绑定（区别于 UI messageId）。 */
  stableMessageId?: string
  /** 当前所属线程；仅和 stableMessageId 同时存在时允许持久化反馈。 */
  threadId?: string
  thinking?: boolean
  initializing?: boolean
  workingText?: string
  /** 初始化阶段（尚未产生文本）的提示文案 */
  initText?: string
  sources?: KnowledgeSource[]
  /** 自定义正文渲染；提供时替代 MarkdownContent(content) */
  contentNode?: ReactNode
  /** 正文之后、操作栏之前的附加内容 */
  children?: ReactNode
  /** 版本切换器（§19.2）：多版本时由上层渲染 `< 1/2 >`。 */
  versionSwitcher?: ReactNode
  onRegenerate?: () => void
  /** 点赞/点踩（含原因）后回调：父级用于 toast / 上报 */
  onFeedback?: (fb: MessageFeedback) => void
  className?: string
}) {
  return (
    <div className={cn("group relative max-w-[82%] max-md:max-w-[94%]", className)}>
      {/* 身份标签：克制的小色点 + 11.5px 名称；连续回答不重复（由上层控制是否传 label） */}
      {label && (
        <div className="mb-1.5 flex items-center gap-1.5">
          {color && <span className="h-[6px] w-[6px] shrink-0 rounded-full" style={{ backgroundColor: color }} />}
          <span className="text-[11.5px] font-[520] text-ink-faint">{label}</span>
          {streaming && (
            <span className="flex items-center gap-1.5 text-[11px] text-ink-faint">
              <span className="working-pulse h-1 w-1 rounded-full bg-current" />
              {workingText}
            </span>
          )}
        </div>
      )}

      <div className="text-[14px] leading-[1.68] tracking-[-0.002em] text-ink">
        {initializing ? (
          <InitIndicator text={initText} />
        ) : (
          contentNode ?? (
            <>
              <MarkdownContent className={cn(streaming && content && !thinking && "typing-cursor")}>
                {content || ""}
              </MarkdownContent>
              {streaming && content && thinking && <ThinkingPulse />}
            </>
          )
        )}
      </div>

      {sources && <Sources sources={sources} />}
      {children}
      {versionSwitcher}

      <FeedbackArea
        messageId={stableMessageId}
        threadId={threadId ?? ""}
        content={content}
        completed={completed}
        onRegenerate={onRegenerate}
        onFeedback={onFeedback}
      />
    </div>
  )
}
