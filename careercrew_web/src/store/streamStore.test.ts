import { beforeEach, describe, expect, it, vi } from "vitest"
import { useStreamStore } from "@/store/streamStore"
import { useChatStore } from "@/store/chatStore"
import { useThreadStore } from "@/store/threadStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

/** 构造一个最小可读的流式 Response：一次 read 吐完整 NDJSON，再 read 返回 done。 */
function streamResponse(lines: string[]) {
  const encoder = new TextEncoder()
  const body = lines.join("\n") + "\n"
  const chunks = [encoder.encode(body)]
  let i = 0
  const reader = {
    read: async () => {
      if (i < chunks.length) {
        const value = chunks[i++]
        return { done: false, value }
      }
      return { done: true, value: undefined }
    },
  }
  return {
    ok: true,
    status: 200,
    body: { getReader: () => reader },
  }
}

describe("streamStore done 解析", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    useChatStore.setState({ messages: [], threadId: "t-legacy" })
    useThreadStore.setState({ currentThreadByModule: { chat: "t-legacy" }, threadsByModule: {} })
    useStreamStore.setState({ sessions: {} })
  })

  it("done 事件把 message_id/turn_id/run_id 挂到该轮 assistant 消息", async () => {
    // 预置一条 streaming assistant 消息（模拟发送时占位）
    useChatStore.setState({
      messages: [
        { id: "ui-1", role: "user", content: "hi" },
        { id: "ui-2", role: "assistant", content: "", streaming: true },
      ],
      threadId: "t-legacy",
    })
    const done = {
      type: "done",
      content: "答案",
      thread_id: "uuid-t1",
      turn_id: "uuid-turn1",
      message_id: "uuid-msg1",
      run_id: "uuid-run1",
      legacy_thread_id: "t-legacy",
      status: "completed",
    }
    apiFetch.mockResolvedValueOnce(streamResponse([JSON.stringify(done)]))

    await useStreamStore.getState().start("t-legacy", "/chat/plan", { intent: "hi", thread_id: "t-legacy" })

    const msgs = useChatStore.getState().messages
    const asst = msgs.find((m) => m.role === "assistant")
    expect(asst?.messageId).toBe("uuid-msg1")
    expect(asst?.turnId).toBe("uuid-turn1")
    expect(asst?.runId).toBe("uuid-run1")
  })

  it("legacy remap：done 的 UUID thread_id 不同 → chatStore/threadStore 更新为新 UUID", async () => {
    useChatStore.setState({ messages: [], threadId: "t-legacy" })
    useThreadStore.setState({
      currentThreadByModule: { chat: "t-legacy" },
      threadsByModule: { chat: [{ thread_id: "t-legacy", title: "旧", module: "chat", pinned: false, persisted: true }] },
    })
    const done = {
      type: "done",
      content: "ans",
      thread_id: "uuid-new",
      turn_id: "uuid-turn",
      message_id: "uuid-msg",
      run_id: "uuid-run",
      legacy_thread_id: "t-legacy",
      status: "completed",
    }
    apiFetch.mockResolvedValueOnce(streamResponse([JSON.stringify(done)]))

    await useStreamStore.getState().start("t-legacy", "/chat/plan", { intent: "hi", thread_id: "t-legacy" })

    expect(useChatStore.getState().threadId).toBe("uuid-new")
    expect(useThreadStore.getState().currentThreadByModule.chat).toBe("uuid-new")
    expect(useThreadStore.getState().threadsByModule.chat?.[0].thread_id).toBe("uuid-new")
    // 流式 session 重新挂到新 id，页面按新 id 仍能查到该流（done 状态）
    const session = useStreamStore.getState().sessions["uuid-new"]
    expect(session).toBeDefined()
    expect(session?.status).toBe("done")
    expect(session?.doneContent).toBe("ans")
    expect(useStreamStore.getState().sessions["t-legacy"]).toBeUndefined()
  })
})
