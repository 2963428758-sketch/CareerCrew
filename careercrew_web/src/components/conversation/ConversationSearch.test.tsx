// @vitest-environment jsdom
import { useRef } from "react"
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { useConversationSearch } from "@/components/conversation/useConversationSearch"
import { ConversationSearchBar } from "@/components/conversation/ConversationSearch"

function Harness({ messages, onWorkspaceRef }: { messages: any[]; onWorkspaceRef?: (el: HTMLElement | null) => void }) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const workspaceRef = useRef<HTMLDivElement | null>(null)
  const s = useConversationSearch(messages, scrollRef, workspaceRef)
  return (
    <div
      ref={(el) => {
        workspaceRef.current = el
        onWorkspaceRef?.(el)
      }}
      onMouseEnter={s.workspaceHoverHandlers.onMouseEnter}
      onMouseLeave={s.workspaceHoverHandlers.onMouseLeave}
      data-testid="workspace"
    >
      <div ref={scrollRef} data-testid="scroll">
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
      </div>
      <ConversationSearchBar
        open={s.open}
        keyword={s.keyword}
        currentIndex={s.currentIndex}
        total={s.total}
        onKeyword={s.setKeyword}
        onPrev={s.prev}
        onNext={s.next}
        onClose={s.close}
      />
    </div>
  )
}

const MSGS = [
  { id: "u1", role: "user", content: "我要找 apple 工作" },
  { id: "a1", role: "assistant", content: "Apple 很好，apple 也有" },
]

describe("useConversationSearch + ConversationSearchBar", () => {
  it("点击搜索图标不拦截时默认关闭；键盘 Ctrl+F 在 workspace 聚焦时打开", () => {
    render(<Harness messages={MSGS} />)
    expect(screen.queryByRole("search")).toBeNull()

    const workspace = screen.getByTestId("workspace")
    const input = document.createElement("textarea")
    workspace.appendChild(input)
    input.focus()
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    expect(screen.getByRole("search")).not.toBeNull()
  })

  it("在 workspace 悬停时 Ctrl+F 打开；Esc 关闭", () => {
    render(<Harness messages={MSGS} />)
    const workspace = screen.getByTestId("workspace")
    fireEvent.mouseEnter(workspace)
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    expect(screen.getByRole("search")).not.toBeNull()

    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.queryByRole("search")).toBeNull()
  })

  it("输入关键词后高亮当前匹配并统计总数；next 循环切换", () => {
    render(<Harness messages={MSGS} />)
    fireEvent.mouseEnter(screen.getByTestId("workspace"))
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })

    fireEvent.change(screen.getByPlaceholderText("搜索对话…"), { target: { value: "apple" } })
    // 3 次出现（u1: 1, a1: 2）
    expect(screen.getByText("1 / 3")).toBeTruthy()

    const nextBtn = screen.getByLabelText("下一个匹配")
    fireEvent.click(nextBtn)
    expect(screen.getByText("2 / 3")).toBeTruthy()
    fireEvent.click(nextBtn)
    expect(screen.getByText("3 / 3")).toBeTruthy()
    fireEvent.click(nextBtn)
    expect(screen.getByText("1 / 3")).toBeTruthy()
  })

  it("prev 按钮反向循环", () => {
    render(<Harness messages={MSGS} />)
    fireEvent.mouseEnter(screen.getByTestId("workspace"))
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    fireEvent.change(screen.getByPlaceholderText("搜索对话…"), { target: { value: "apple" } })

    fireEvent.click(screen.getByLabelText("上一个匹配"))
    expect(screen.getByText("3 / 3")).toBeTruthy()
  })

  it("非 workspace 焦点/悬停时 Ctrl+F 不拦截（不打开搜索）", () => {
    render(<Harness messages={MSGS} />)
    // 焦点在 body（非 workspace）
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    expect(screen.queryByRole("search")).toBeNull()
  })

  it("当前匹配调用 scrollIntoView（通过 mark 定位）", () => {
    render(<Harness messages={MSGS} />)
    fireEvent.mouseEnter(screen.getByTestId("workspace"))
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    fireEvent.change(screen.getByPlaceholderText("搜索对话…"), { target: { value: "apple" } })

    const marks = document.querySelectorAll("mark.search-mark")
    expect(marks).toHaveLength(1)
    expect(marks[0].getAttribute("data-search-current")).toBe("true")
  })
})
