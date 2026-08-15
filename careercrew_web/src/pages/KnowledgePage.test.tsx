// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import KnowledgePage from "@/pages/KnowledgePage"
import { useThreadStore } from "@/store/threadStore"
import { useStreamStore } from "@/store/streamStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

describe("KnowledgePage 检索范围", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    apiFetch.mockImplementation(async () => ({ ok: true, status: 200, json: async () => [] }))
    useStreamStore.setState({ sessions: {} })
    useThreadStore.setState({
      threadsByModule: {
        knowledge: [
          { thread_id: "k-a", title: "A", module: "knowledge", pinned: false, persisted: true },
          {
            thread_id: "k-b",
            title: "B",
            module: "knowledge",
            pinned: false,
            persisted: true,
            retrieval_scope: { type: "all", category_id: "interview" },
          },
        ],
      },
      currentThreadByModule: { knowledge: "k-a" },
    })
  })

  it("点击分类立即 PATCH 范围（保留当前可见范围）", async () => {
    render(<KnowledgePage />)
    fireEvent.click(screen.getByText("面试题"))
    await waitFor(() =>
      expect(
        apiFetch.mock.calls.some(
          (c) =>
            c[0] === "/api/threads/k-a" &&
            (c[1] as Record<string, unknown>)?.method === "PATCH"
        )
      ).toBe(true)
    )
    const patchCall = apiFetch.mock.calls.find(
      (c) =>
        c[0] === "/api/threads/k-a" &&
        (c[1] as Record<string, unknown>)?.method === "PATCH"
    )!
    const body = JSON.parse((patchCall[1] as { body: string }).body)
    expect(body.retrieval_scope).toEqual({ type: "all", category_id: "interview" })
  })

  it("范围与分类正交：选公共库后再选面试题，两者同时保留", async () => {
    render(<KnowledgePage />)
    fireEvent.click(screen.getByText("公共库"))
    await waitFor(() => expect(screen.getByText(/当前：公共库 · 全部分类/)).toBeTruthy())
    fireEvent.click(screen.getByText("面试题"))
    await waitFor(() => expect(screen.getByText(/当前：公共库 · 面试题/)).toBeTruthy())
    const patchCall = apiFetch.mock.calls.findLast(
      (c) =>
        c[0] === "/api/threads/k-a" &&
        (c[1] as Record<string, unknown>)?.method === "PATCH"
    )!
    const body = JSON.parse((patchCall[1] as { body: string }).body)
    expect(body.retrieval_scope).toEqual({ type: "public", category_id: "interview" })
  })

  it("切换会话恢复其保存的范围", async () => {
    render(<KnowledgePage />)
    expect(screen.getByText(/当前：全部 · 全部分类/)).toBeTruthy()
    useThreadStore.getState().selectThread("knowledge", "k-b")
    await waitFor(() => expect(screen.getByText(/当前：全部 · 面试题/)).toBeTruthy())
  })

  it("无保存范围的历史会话回退为全部", async () => {
    render(<KnowledgePage />)
    await waitFor(() => expect(screen.getByText(/当前：全部 · 全部分类/)).toBeTruthy())
  })
})
