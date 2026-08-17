import { beforeEach, describe, expect, it, vi } from "vitest"
import { useThreadStore } from "@/store/threadStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

describe("threadStore retrieval_scope", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    useThreadStore.setState({ threadsByModule: {}, currentThreadByModule: {} })
  })

  it("fetchThreads 解析新模型 retrieval_scope", async () => {
    apiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          thread_id: "k-1",
          title: "t",
          module: "knowledge",
          pinned: false,
          retrieval_scope: { type: "public", category_id: "resume" },
        },
      ],
    })
    await useThreadStore.getState().fetchThreads("knowledge")
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toEqual({
      type: "public",
      category_id: "resume",
    })
  })

  it("历史会话旧格式归一化为 type=all + category_id", async () => {
    apiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          thread_id: "k-legacy",
          title: "t",
          module: "knowledge",
          pinned: false,
          retrieval_scope: { type: "category", category_id: "interview" },
        },
      ],
    })
    await useThreadStore.getState().fetchThreads("knowledge")
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toEqual({
      type: "all",
      category_id: "interview",
    })
  })

  it("历史会话无字段时 retrieval_scope 为 null", async () => {
    apiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { thread_id: "k-none", title: "t", module: "knowledge", pinned: false },
      ],
    })
    await useThreadStore.getState().fetchThreads("knowledge")
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toBeNull()
  })

  it("setThreadScope 对已落库会话乐观更新并 PATCH", async () => {
    apiFetch.mockResolvedValueOnce({ ok: true, status: 200 })
    useThreadStore.setState({
      threadsByModule: {
        knowledge: [
          { thread_id: "k-1", title: "t", module: "knowledge", pinned: false, persisted: true },
        ],
      },
    })
    await useThreadStore.getState().setThreadScope("knowledge", "k-1", {
      type: "private", category_id: "job",
    })
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/threads/k-1",
      expect.objectContaining({ method: "PATCH" })
    )
    expect(JSON.parse(apiFetch.mock.calls[0][1].body).retrieval_scope).toEqual({
      type: "private", category_id: "job",
    })
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toEqual({
      type: "private", category_id: "job",
    })
  })

  it("未落库会话只保留本地占位：不 PATCH、不显示为已持久化", async () => {
    await useThreadStore.getState().setThreadScope("knowledge", "k-fresh", { type: "public" })
    expect(apiFetch).not.toHaveBeenCalled()
    const row = useThreadStore.getState().threadsByModule.knowledge?.find(
      (t) => t.thread_id === "k-fresh"
    )
    expect(row?.retrieval_scope).toEqual({ type: "public" })
    expect(row?.persisted).toBe(false)
  })

  it("touchThread 对已落库会话 PATCH 携带范围；404 时 POST 创建并携带范围", async () => {
    useThreadStore.setState({
      threadsByModule: {
        knowledge: [
          {
            thread_id: "k-1", title: "k-1", module: "knowledge", pinned: false,
            persisted: true, retrieval_scope: { type: "public" },
          },
        ],
      },
    })
    apiFetch.mockResolvedValueOnce({ ok: true, status: 200 })
    await useThreadStore.getState().touchThread("knowledge", "k-1", "你好")
    expect(JSON.parse(apiFetch.mock.calls[0][1].body).retrieval_scope).toEqual({ type: "public" })

    apiFetch.mockReset()
    apiFetch.mockResolvedValueOnce({ ok: false, status: 404 })
    apiFetch.mockResolvedValueOnce({ ok: true, status: 200 })
    useThreadStore.setState({ threadsByModule: {} })
    await useThreadStore.getState().setThreadScope("knowledge", "k-2", {
      type: "private", category_id: "resume",
    })
    await useThreadStore.getState().touchThread("knowledge", "k-2", "你好")
    expect(apiFetch.mock.calls[1][0]).toBe("/api/threads")
    expect(apiFetch.mock.calls[1][1].method).toBe("POST")
    expect(JSON.parse(apiFetch.mock.calls[1][1].body).retrieval_scope).toEqual({
      type: "private", category_id: "resume",
    })
  })

  it("remapLegacyThread 把旧 legacy id 替换为新 UUID（线程条目 + currentThreadByModule + unread）", () => {
    useThreadStore.setState({
      threadsByModule: {
        chat: [{ thread_id: "t-legacy", title: "旧", module: "chat", pinned: false, persisted: true }],
      },
      currentThreadByModule: { chat: "t-legacy" },
      completedUnread: { "t-legacy": true },
    })
    useThreadStore.getState().remapLegacyThread("t-legacy", "uuid-new")
    const st = useThreadStore.getState()
    expect(st.currentThreadByModule.chat).toBe("uuid-new")
    expect(st.threadsByModule.chat[0].thread_id).toBe("uuid-new")
    expect(st.completedUnread["uuid-new"]).toBe(true)
    expect(st.completedUnread["t-legacy"]).toBeUndefined()
  })

  it("remapLegacyThread 对非当前 id 的 legacy 不误改", () => {
    useThreadStore.setState({
      threadsByModule: {
        chat: [{ thread_id: "other", title: "o", module: "chat", pinned: false, persisted: true }],
      },
      currentThreadByModule: { chat: "other" },
    })
    useThreadStore.getState().remapLegacyThread("t-missing", "uuid-new")
    const st = useThreadStore.getState()
    expect(st.currentThreadByModule.chat).toBe("other")
  })
})
