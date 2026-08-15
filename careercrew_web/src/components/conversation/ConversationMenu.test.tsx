// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ConversationMenu } from "@/components/conversation/ConversationMenu"
import { useThreadStore } from "@/store/threadStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

function openMenu() {
  fireEvent.click(screen.getByLabelText("更多"))
}

describe("ConversationMenu", () => {
  let renameSpy: ReturnType<typeof vi.fn>
  let deleteSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    apiFetch.mockReset()
    apiFetch.mockResolvedValue({ ok: true, status: 200, text: async () => "# 标题" })
    renameSpy = vi.fn(async () => {})
    deleteSpy = vi.fn(async () => {})
    vi.spyOn(useThreadStore, "getState").mockReturnValue({
      renameThread: renameSpy,
      deleteThread: deleteSpy,
      copyThreadId: vi.fn(async () => {}),
    } as never)
  })

  it("渲染触发器并展开六项菜单", () => {
    render(<ConversationMenu threadId="t-1" title="求职咨询" module="chat" />)
    expect(screen.getByLabelText("更多")).toBeTruthy()
    openMenu()
    expect(screen.getByText("重命名")).toBeTruthy()
    expect(screen.getByText("复制会话 ID")).toBeTruthy()
    expect(screen.getByText("导出 Markdown")).toBeTruthy()
    expect(screen.getByText("导出 JSON")).toBeTruthy()
    expect(screen.getByText("清空消息")).toBeTruthy()
    expect(screen.getByText("删除会话")).toBeTruthy()
  })

  it("点击「清空消息」弹出二次确认对话框", () => {
    render(<ConversationMenu threadId="t-1" title="求职咨询" module="chat" />)
    openMenu()
    fireEvent.click(screen.getByText("清空消息"))
    expect(screen.getByText(/会话与标题会保留/)).toBeTruthy()
  })

  it("点击「删除会话」弹出二次确认对话框并在确认后删除", () => {
    render(<ConversationMenu threadId="t-1" title="求职咨询" module="chat" />)
    openMenu()
    fireEvent.click(screen.getByText("删除会话"))
    expect(screen.getByText(/无法恢复/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "删除" }))
    // 删除确认后触发 threadStore.deleteThread（异步）
    expect(deleteSpy).toHaveBeenCalled()
  })

  it("点击「重命名」进入内联输入并提交", () => {
    render(<ConversationMenu threadId="t-1" title="求职咨询" module="chat" />)
    openMenu()
    fireEvent.click(screen.getByText("重命名"))
    const input = screen.getByPlaceholderText("新标题")
    fireEvent.change(input, { target: { value: "新标题" } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(renameSpy).toHaveBeenCalledWith("chat", "t-1", "新标题")
  })

  it("点击「导出 Markdown」调用后端导出端点", () => {
    render(<ConversationMenu threadId="t-1" title="求职咨询" module="chat" />)
    openMenu()
    fireEvent.click(screen.getByText("导出 Markdown"))
    expect(apiFetch).toHaveBeenCalledWith("/api/threads/t-1/export?format=md")
  })

  it("点击「导出 JSON」调用后端导出端点", () => {
    render(<ConversationMenu threadId="t-1" title="求职咨询" module="chat" />)
    openMenu()
    fireEvent.click(screen.getByText("导出 JSON"))
    expect(apiFetch).toHaveBeenCalledWith("/api/threads/t-1/export?format=json")
  })
})
