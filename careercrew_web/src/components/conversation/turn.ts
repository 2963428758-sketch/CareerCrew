import type { ChatMessage } from "@/types"

/**
 * 一轮对话（Turn）：一次用户提问 + 紧随其后的助手回答。
 * Anchor / Rail Marker 与 userMessage 一一对应。
 * §19：同一 turn 的 assistant 可有多版本（regenerate 追加新版本，不覆盖旧消息）；
 * `assistant` 始终指向最新版本（默认展示），`versions` 保序保留全部版本（旧 → 新）。
 * 泛型：各对话页可以携带自己的扩展字段（sources / score / opinions 等）。
 */
export interface ConversationTurn<T = ChatMessage> {
  id: string
  user: T
  assistant?: T
  /** 该 turn 的全部 assistant 版本（含最新一条）。单版本时与 [assistant] 等价。 */
  versions?: T[]
}

/**
 * 把扁平消息流分组为 Turn。孤儿 assistant 消息（历史异常）挂到合成的空 Turn 上。
 * 同一 turn 下连续的 assistant 消息（共享 turnId 或紧随用户消息之后）按出现顺序
 * 归入 versions，最后一条为最新版本。
 */
export function groupTurns<T extends { id: string; role: "user" | "assistant"; turnId?: string }>(messages: T[]): ConversationTurn<T>[] {
  const turns: ConversationTurn<T>[] = []
  for (const m of messages) {
    if (m.role === "user") {
      turns.push({ id: m.id, user: m })
    } else {
      const last = turns[turns.length - 1]
      const matched = m.turnId
        ? turns.find((t) => t.id === m.turnId || t.assistant?.turnId === m.turnId || t.user.turnId === m.turnId)
        : last
      if (matched && !matched.assistant) {
        matched.assistant = m
        matched.versions = [m]
      } else if (matched) {
        matched.versions = [...(matched.versions ?? [matched.assistant!]), m]
        matched.assistant = m
      } else {
        turns.push({ id: m.id, user: m, assistant: m, versions: [m] })
      }
    }
  }
  return turns
}

/** anchor id：与 turn.id 一致，rail 点击滚动目标。 */
export const turnAnchorId = (turnId: string) => `turn-${turnId}`
