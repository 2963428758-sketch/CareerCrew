import type { KnowledgeSource, MessageAttachment } from "@/types"

/** 知识库问答页消息模型（restoreHistory 映射 + 流式占位共用）。 */
export interface KnowledgeMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
  sources?: KnowledgeSource[]
  messageId?: string
  turnId?: string
  runId?: string
  attachments?: MessageAttachment[]
}

let msgId = 0
export const nextId = () => `kb-msg-${++msgId}`
