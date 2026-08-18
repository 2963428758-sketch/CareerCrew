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

  it("done 携带当前 legacy_thread_id 时不切换当前会话身份", async () => {
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

    expect(useChatStore.getState().threadId).toBe("t-legacy")
    expect(useThreadStore.getState().currentThreadByModule.chat).toBe("t-legacy")
    expect(useThreadStore.getState().threadsByModule.chat?.[0].thread_id).toBe("t-legacy")
    // canonical UUID 仍保存在 doneIds，但流式 session 继续使用 legacy key。
    const session = useStreamStore.getState().sessions["t-legacy"]
    expect(session).toBeDefined()
    expect(session?.status).toBe("done")
    expect(session?.doneContent).toBe("ans")
    expect(useStreamStore.getState().sessions["uuid-new"]).toBeUndefined()
  })

  it("legacy_thread_id 匹配时 stop(legacy id) 能 abort 在途请求", async () => {
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
    // 一次 read 吐 done（触发 remap），第二次 read 挂起等待 abort 才 resolve
    const encoder = new TextEncoder()
    const body = JSON.stringify(done) + "\n"
    let signal: AbortSignal | undefined
    const chunks = [encoder.encode(body)]
    let i = 0
    apiFetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      signal = init?.signal as AbortSignal | undefined
      const reader = {
        read: async () => {
          if (i < chunks.length) {
            const value = chunks[i++]
            return { done: false, value }
          }
          if (signal?.aborted) return { done: true, value: undefined }
          await new Promise<void>((resolve) => signal?.addEventListener("abort", () => resolve(), { once: true }))
          return { done: true, value: undefined }
        },
      }
      return { ok: true, status: 200, body: { getReader: () => reader } } as unknown as Response
    })

    const startP = useStreamStore.getState().start("t-legacy", "/chat/plan", { intent: "hi", thread_id: "t-legacy" })
    // 等 done 行被消费（session 仍挂在 legacy id）
    await vi.waitFor(() => {
      expect(useStreamStore.getState().sessions["t-legacy"]).toBeDefined()
    })
    expect(signal?.aborted).toBe(false)
    // 关键：用 legacy id 停止，应命中原 controller 并 abort 在途 fetch。
    useStreamStore.getState().stop("t-legacy")
    await startP
    expect(signal?.aborted).toBe(true)
  })
})

describe("streamStore.regenerate（§19）", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    useChatStore.setState({ messages: [], threadId: "t-legacy" })
    useThreadStore.setState({ currentThreadByModule: { chat: "t-legacy" }, threadsByModule: {} })
    useStreamStore.setState({ sessions: {} })
  })

  it("POST /api/messages/{id}/regenerate，done 追加新版本不覆盖旧消息", async () => {
    // 历史：一条已完成的 assistant（v1）+ 一个 regenerate 流式占位（空内容、带 turnId）
    useChatStore.setState({
      messages: [
        { id: "u1", role: "user", content: "q" },
        { id: "a1", role: "assistant", content: "旧答案", messageId: "m-hist", turnId: "turn-1", runId: "r-hist" },
        { id: "a2", role: "assistant", content: "", messageId: undefined, turnId: "turn-1", streaming: true },
      ],
      threadId: "t-legacy",
    })
    const done = {
      type: "done",
      content: "新答案",
      thread_id: "t-legacy",
      turn_id: "turn-1",
      message_id: "uuid-new-msg",
      run_id: "uuid-new-run",
      regenerated_from_message_id: "m-hist",
      status: "completed",
    }
    apiFetch.mockResolvedValueOnce(streamResponse([JSON.stringify(done)]))

    await useStreamStore.getState().regenerate("t-legacy", "m-hist")

    // 断言请求路径
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/messages/m-hist/regenerate",
      expect.objectContaining({ method: "POST" })
    )

    const msgs = useChatStore.getState().messages
    // 旧消息仍在且未被 mutate
    const old = msgs.find((m) => m.messageId === "m-hist")
    expect(old?.content).toBe("旧答案")
    // 新版本追加（占位符被原位替换为新消息）
    const newMsg = msgs.find((m) => m.messageId === "uuid-new-msg")
    expect(newMsg?.content).toBe("新答案")
    expect(newMsg?.turnId).toBe("turn-1")
    expect(newMsg?.runId).toBe("uuid-new-run")
    expect(newMsg?.regeneratedFromMessageId).toBe("m-hist")
    expect(newMsg?.streaming).toBe(false)
  })

  it("占位符（空内容）被替换而非追加，messages 里不残留空 assistant", async () => {
    useChatStore.setState({
      messages: [
        { id: "u1", role: "user", content: "q" },
        { id: "a2", role: "assistant", content: "", turnId: "turn-1", streaming: true },
      ],
      threadId: "t-legacy",
    })
    const done = {
      type: "done",
      content: "答案",
      thread_id: "t-legacy",
      turn_id: "turn-1",
      message_id: "uuid-msg",
      run_id: "uuid-run",
      regenerated_from_message_id: "m-old",
      status: "completed",
    }
    apiFetch.mockResolvedValueOnce(streamResponse([JSON.stringify(done)]))

    await useStreamStore.getState().regenerate("t-legacy", "m-old")

    const assistants = useChatStore.getState().messages.filter((m) => m.role === "assistant")
    expect(assistants).toHaveLength(1)
    expect(assistants[0].content).toBe("答案")
    expect(assistants[0].messageId).toBe("uuid-msg")
  })
})
