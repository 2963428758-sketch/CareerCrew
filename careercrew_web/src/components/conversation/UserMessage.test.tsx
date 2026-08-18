// @vitest-environment jsdom
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { UserMessage } from "@/components/conversation/UserMessage"

vi.mock("@/components/conversation/copy", () => ({
  copyText: vi.fn(),
}))

vi.mock("@/store/threadStore", () => ({
  useThreadStore: {
    getState: () => ({
      currentThreadByModule: { chat: "t-1" },
      copyThreadId: vi.fn(),
    }),
  },
}))

describe("UserMessage", () => {
  it("把附件渲染在用户消息气泡上方", () => {
    render(
      <UserMessage
        content="请分析"
        attachments={[{ id: "a-1", filename: "report.pdf", kind: "document" }]}
      />,
    )

    const attachment = screen.getByTestId("message-attachment")
    const bubble = screen.getByTestId("user-message-bubble")
    expect(attachment.compareDocumentPosition(bubble) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(attachment.textContent).toContain("report.pdf")
  })
})
