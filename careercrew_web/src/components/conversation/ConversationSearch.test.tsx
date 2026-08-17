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

/** 渲染 markdown 富文本（加粗/斜体/链接内嵌关键词），模拟 AssistantMessage 的实际渲染。 */
function renderMarkdown(content: string) {
  // 逐段解析 `**bold**`、`*em*`、`[text](url)`，其余作为纯文本节点
  const parts: string[] = content.split(/(\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]*\))/g)
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**"))
      return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith("*") && p.endsWith("*"))
      return <em key={i}>{p.slice(1, -1)}</em>
    const m = p.match(/^\[([^\]]+)\]\(([^)]*)\)$/)
    if (m)
      return (
        <a key={i} href={m[2]}>
          {m[1]}
        </a>
      )
    return p
  })
}

function MarkdownHarness({ messages }: { messages: any[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const workspaceRef = useRef<HTMLDivElement | null>(null)
  const s = useConversationSearch(messages, scrollRef, workspaceRef)
  return (
    <div
      ref={(el) => {
        workspaceRef.current = el
      }}
      onMouseEnter={s.workspaceHoverHandlers.onMouseEnter}
      onMouseLeave={s.workspaceHoverHandlers.onMouseLeave}
      data-testid="workspace"
    >
      <div ref={scrollRef} data-testid="scroll">
        {messages.map((m) => (
          <p key={m.id}>{renderMarkdown(m.content)}</p>
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

  it("非 workspace 焦点/悬停时 Esc 不拦截（搜索条保持打开）", () => {
    render(<Harness messages={MSGS} />)
    // 先在 workspace 悬停时打开搜索条
    fireEvent.mouseEnter(screen.getByTestId("workspace"))
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    expect(screen.getByRole("search")).not.toBeNull()

    // 移出 workspace 且失焦（非聚焦/悬停）后按 Esc：不关闭
    fireEvent.mouseLeave(screen.getByTestId("workspace"))
    ;(document.activeElement as HTMLElement | null)?.blur()
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.getByRole("search")).not.toBeNull()
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

  it("关键词落在 markdown 加粗/链接内时，计数与高亮一致（共享渲染文本域）", () => {
    const mdMsgs = [
      { id: "u1", role: "user", content: "我要找 apple 工作" },
      // apple 出现在加粗与链接内；渲染后 textContent 各含一次 "apple"
      { id: "a1", role: "assistant", content: "看 **apple** 与 [apple](/x) 的位置" },
    ]
    render(<MarkdownHarness messages={mdMsgs} />)
    fireEvent.mouseEnter(screen.getByTestId("workspace"))
    fireEvent.keyDown(document, { key: "f", ctrlKey: true })
    fireEvent.change(screen.getByPlaceholderText("搜索对话…"), { target: { value: "apple" } })

    // 渲染文本域：u1 一次 + a1 两次 = 3；与高亮共享同一列表
    expect(screen.getByText("1 / 3")).toBeTruthy()

    // 跳到第 2 项，高亮应落在 a1 的加粗 <strong> 内（渲染文本第 2 次出现）
    fireEvent.click(screen.getByLabelText("下一个匹配"))
    const mark = document.querySelector("mark.search-mark")
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe("apple")
    expect(mark!.parentElement?.tagName).toBe("STRONG")

    // 第 3 项落在链接 <a> 内
    fireEvent.click(screen.getByLabelText("下一个匹配"))
    const mark3 = document.querySelector("mark.search-mark")
    expect(mark3).not.toBeNull()
    expect(mark3!.parentElement?.tagName).toBe("A")
    expect(screen.getByText("3 / 3")).toBeTruthy()
  })
})
