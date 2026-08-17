// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import KnowledgePage from "@/pages/KnowledgePage"
import { resetFeedbackStateForTest } from "@/lib/feedbackState"
import { useThreadStore } from "@/store/threadStore"
import { useStreamStore } from "@/store/streamStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

const jsonResponse = (body: unknown) => ({ ok: true, status: 200, json: async () => body })

describe("KnowledgePage 检索范围", () => {
  beforeEach(() => {
    resetFeedbackStateForTest()
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

  it("稳定 ID 的再生成保留版本，并把反馈按每个版本独立渲染", async () => {
    const regenerate = vi.fn().mockResolvedValue(undefined)
    apiFetch.mockImplementation(async (url: string) => {
      if (url === "/api/threads/k-a/messages") {
        return jsonResponse([
          { id: "question-1", role: "user", content: "如何准备面试？", turn_id: "turn-1" },
          { id: "answer-v1", role: "assistant", content: "旧版本", turn_id: "turn-1", run_id: "run-1" },
          { id: "answer-v2", role: "assistant", content: "新版本", turn_id: "turn-1", run_id: "run-2" },
        ])
      }
      if (url === "/api/threads/k-a/feedback") {
        return jsonResponse([{ id: "feedback-v1", message_id: "answer-v1", rating: "positive", share_context: false }])
      }
      return jsonResponse([])
    })
    useStreamStore.setState({ sessions: {}, regenerate })

    render(<KnowledgePage />)

    await waitFor(() => expect(screen.getByText("新版本")).toBeTruthy())
    expect(screen.getByText("2 / 2")).toBeTruthy()
    expect(screen.getByRole("button", { name: "有帮助" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "重新生成" }))
    await waitFor(() => expect(regenerate).toHaveBeenCalledWith("k-a", "answer-v2"))

    fireEvent.click(screen.getByRole("button", { name: "上一个版本" }))
    expect(screen.getByText("旧版本")).toBeTruthy()
    await waitFor(() => expect(screen.getByRole("button", { name: "取消反馈" })).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "下一个版本" }))
    expect(screen.getByText("新版本")).toBeTruthy()
    expect(screen.getByRole("button", { name: "有帮助" })).toBeTruthy()
  })

  it("遗留无稳定 ID 的回答隐藏反馈但保留复制和兼容再生成", async () => {
    const start = vi.fn().mockResolvedValue(undefined)
    apiFetch.mockImplementation(async (url: string) => {
      if (url === "/api/threads/k-a/messages") {
        return jsonResponse([
          { id: "question-legacy", role: "user", content: "旧问题", turn_id: "turn-legacy" },
          { role: "assistant", content: "旧回答", turn_id: "turn-legacy" },
        ])
      }
      return jsonResponse([])
    })
    useStreamStore.setState({ sessions: {}, start })

    render(<KnowledgePage />)

    await waitFor(() => expect(screen.getByText("旧回答")).toBeTruthy())
    expect(screen.getByRole("button", { name: "复制回答" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "重新生成" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "有帮助" })).toBeNull()
    expect(screen.queryByRole("button", { name: "不满意" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "重新生成" }))
    await waitFor(() => expect(start).toHaveBeenCalledWith(
      "k-a",
      "/knowledge/ask",
      { question: "旧问题", thread_id: "k-a", category: "", scope: "all" },
    ))
  })
})
