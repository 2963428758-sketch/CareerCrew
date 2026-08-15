import type { ChatMessage } from "@/types"

/**
 * 一轮对话（Turn）：一次用户提问 + 紧随其后的助手回答。
 * Anchor / Rail Marker 与 userMessage 一一对应。
 * 泛型：各对话页可以携带自己的扩展字段（sources / score / opinions 等）。
 */
export interface ConversationTurn<T = ChatMessage> {
  id: string
  user: T
  assistant?: T
}

/** 把扁平消息流分组为 Turn。孤儿 assistant 消息（历史异常）挂到合成的空 Turn 上。 */
export function groupTurns<T extends { id: string; role: "user" | "assistant" }>(messages: T[]): ConversationTurn<T>[] {
  const turns: ConversationTurn<T>[] = []
  for (const m of messages) {
    if (m.role === "user") {
      turns.push({ id: m.id, user: m })
    } else {
      const last = turns[turns.length - 1]
      if (last && !last.assistant) {
        last.assistant = m
      } else {
        // 没有前置用户消息的 assistant：仅作为回答兜底展示（无 anchor marker）
        turns.push({ id: m.id, user: m, assistant: m })
      }
    }
  }
  return turns
}

/** anchor id：与 turn.id 一致，rail 点击滚动目标。 */
export const turnAnchorId = (turnId: string) => `turn-${turnId}`
