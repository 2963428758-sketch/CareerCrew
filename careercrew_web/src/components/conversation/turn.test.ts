import { describe, expect, it } from "vitest"
import { groupTurns } from "@/components/conversation/turn"
import type { ChatMessage } from "@/types"

function msg(id: string, role: "user" | "assistant", content: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return { id, role, content, ...extra }
}

describe("groupTurns 多版本分组（§19）", () => {
  it("单版本：assistant 与 versions=[assistant]", () => {
    const messages: ChatMessage[] = [
      msg("u1", "user", "q"),
      msg("a1", "assistant", "ans", { messageId: "m1", turnId: "t1", runId: "r1" }),
    ]
    const turns = groupTurns(messages)
    expect(turns).toHaveLength(1)
    expect(turns[0].assistant?.content).toBe("ans")
    expect(turns[0].versions).toEqual([turns[0].assistant])
  })

  it("同一 turnId 的两个 assistant 归入 versions，最新为 assistant", () => {
    const messages: ChatMessage[] = [
      msg("u1", "user", "q", { turnId: "t1" }),
      msg("a1", "assistant", "v1", { messageId: "m1", turnId: "t1", runId: "r1" }),
      msg("a2", "assistant", "v2", { messageId: "m2", turnId: "t1", runId: "r2", regeneratedFromMessageId: "m1" }),
    ]
    const turns = groupTurns(messages)
    expect(turns).toHaveLength(1)
    expect(turns[0].versions?.map((v) => v.content)).toEqual(["v1", "v2"])
    expect(turns[0].assistant?.content).toBe("v2")
    expect(turns[0].assistant?.messageId).toBe("m2")
  })

  it("旧版本对象不被 mutate（versions 保留原始引用内容不变）", () => {
    const v1 = msg("a1", "assistant", "v1", { messageId: "m1", turnId: "t1" })
    const v2 = msg("a2", "assistant", "v2", { messageId: "m2", turnId: "t1" })
    const messages: ChatMessage[] = [msg("u1", "user", "q", { turnId: "t1" }), v1, v2]
    groupTurns(messages)
    expect(v1.content).toBe("v1")
    expect(v2.content).toBe("v2")
    expect(v1.messageId).toBe("m1")
  })

  it("无 turnId 的连续 assistant 仍紧随后续（不误判为同版本）", () => {
    // 无共享 turnId 时，第二个 assistant 是孤儿（挂到合成 turn），不是版本
    const messages: ChatMessage[] = [
      msg("u1", "user", "q"),
      msg("a1", "assistant", "v1", { messageId: "m1" }),
    ]
    const turns = groupTurns(messages)
    expect(turns).toHaveLength(1)
    expect(turns[0].versions).toEqual([turns[0].assistant])
  })
})
