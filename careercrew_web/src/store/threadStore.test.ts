import { beforeEach, describe, expect, it, vi } from "vitest"
import { useThreadStore } from "@/store/threadStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

describe("threadStore retrieval_scope", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    useThreadStore.setState({ threadsByModule: {}, currentThreadByModule: {} })
  })

  it("fetchThreads 解析 retrieval_scope", async () => {
    apiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          thread_id: "k-1",
          title: "t",
          module: "knowledge",
          pinned: false,
          retrieval_scope: { type: "category", category_id: "resume" },
        },
      ],
    })
    await useThreadStore.getState().fetchThreads("knowledge")
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toEqual({
      type: "category",
      category_id: "resume",
    })
  })

  it("历史会话无字段时 retrieval_scope 为 null", async () => {
    apiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { thread_id: "k-legacy", title: "t", module: "knowledge", pinned: false },
      ],
    })
    await useThreadStore.getState().fetchThreads("knowledge")
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toBeNull()
  })

  it("setThreadScope 乐观更新并 PATCH", async () => {
    apiFetch.mockResolvedValueOnce({ ok: true, status: 200 })
    useThreadStore.setState({
      threadsByModule: {
        knowledge: [{ thread_id: "k-1", title: "t", module: "knowledge", pinned: false }],
      },
    })
    await useThreadStore.getState().setThreadScope("knowledge", "k-1", { type: "all" })
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/threads/k-1",
      expect.objectContaining({ method: "PATCH" })
    )
    expect(JSON.parse(apiFetch.mock.calls[0][1].body).retrieval_scope).toEqual({ type: "all" })
    expect(useThreadStore.getState().threadsByModule.knowledge[0].retrieval_scope).toEqual({
      type: "all",
    })
  })

  it("PATCH 404 时回退 POST 创建", async () => {
    apiFetch.mockResolvedValueOnce({ ok: false, status: 404 })
    apiFetch.mockResolvedValueOnce({ ok: true, status: 200 })
    await useThreadStore.getState().setThreadScope("knowledge", "k-new", { type: "all" })
    expect(apiFetch.mock.calls[1][0]).toBe("/api/threads")
    expect(apiFetch.mock.calls[1][1].method).toBe("POST")
  })
})
