// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MentionPicker } from "@/components/prompt/MentionPicker"
import type { ContextResource } from "@/lib/contextResources"

// ---- 依赖桩：lib 层 mock，隔离组件行为 ----
const fetchContextResources = vi.hoisted(() => vi.fn())
vi.mock("@/lib/contextResources", () => ({
  fetchContextResources,
  debounce: (fn: (...a: unknown[]) => void, _ms?: number) => fn,
  MENTION_TYPE_LABEL: {
    knowledge_document: "知识文档",
    resume: "简历",
  },
}))

function resource(overrides: Partial<ContextResource> = {}): ContextResource {
  return {
    type: "knowledge_document",
    id: "doc-1",
    name: "RAG 技术笔记",
    visibility: "private",
    ...overrides,
  }
}

describe("MentionPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchContextResources.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it("打开后搜索并展示结果", async () => {
    fetchContextResources.mockResolvedValue([resource()])
    render(<MentionPicker />)

    fireEvent.click(screen.getByRole("button", { name: "引用资料" }))
    const input = screen.getByTestId("mention-search-input")
    fireEvent.change(input, { target: { value: "RAG" } })

    const results = await screen.findAllByTestId("mention-result")
    expect(results).toHaveLength(1)
    expect(results[0].textContent).toContain("RAG 技术笔记")
    expect(fetchContextResources).toHaveBeenCalledWith({ q: "RAG" })
  })

  it("选择结果 → 生成 chip 并触发 onMentionsChange", async () => {
    fetchContextResources.mockResolvedValue([resource()])
    const onChange = vi.fn()
    render(<MentionPicker onMentionsChange={onChange} />)

    fireEvent.click(screen.getByRole("button", { name: "引用资料" }))
    fireEvent.change(screen.getByTestId("mention-search-input"), { target: { value: "RAG" } })

    const result = await screen.findByTestId("mention-result")
    fireEvent.click(result)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith([{ type: "knowledge_document", id: "doc-1" }])
    })
    expect(screen.getByTestId("mention-chip").textContent).toContain("RAG 技术笔记")
  })

  it("再次点击已选结果 → 取消选中并移除 chip", async () => {
    fetchContextResources.mockResolvedValue([resource()])
    const onChange = vi.fn()
    render(<MentionPicker onMentionsChange={onChange} />)

    fireEvent.click(screen.getByRole("button", { name: "引用资料" }))
    fireEvent.change(screen.getByTestId("mention-search-input"), { target: { value: "RAG" } })
    fireEvent.click(await screen.findByTestId("mention-result"))

    await waitFor(() => expect(screen.getByTestId("mention-chip")).toBeDefined())
    // 再次点击（下拉仍在）取消选中
    fireEvent.click(screen.getByTestId("mention-result"))
    await waitFor(() => {
      expect(screen.queryByTestId("mention-chip")).toBeNull()
      expect(onChange).toHaveBeenLastCalledWith([])
    })
  })

  it("删除 chip 触发回调移除该项", async () => {
    fetchContextResources.mockResolvedValue([resource()])
    const onChange = vi.fn()
    render(<MentionPicker onMentionsChange={onChange} />)

    fireEvent.click(screen.getByRole("button", { name: "引用资料" }))
    fireEvent.change(screen.getByTestId("mention-search-input"), { target: { value: "RAG" } })
    fireEvent.click(await screen.findByTestId("mention-result"))
    await screen.findByTestId("mention-chip")

    fireEvent.click(screen.getByRole("button", { name: "移除 RAG 技术笔记" }))
    await waitFor(() => {
      expect(screen.queryByTestId("mention-chip")).toBeNull()
      expect(onChange).toHaveBeenLastCalledWith([])
    })
  })
})
