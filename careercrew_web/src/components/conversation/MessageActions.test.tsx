// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { MessageActions } from "@/components/conversation/MessageActions"

const noop = () => {}

function renderActions(overrides: Partial<Parameters<typeof MessageActions>[0]> = {}) {
  const props = {
    content: "回答内容",
    feedback: null,
    onCopy: noop,
    onToggleLike: noop,
    onToggleDislike: noop,
    ...overrides,
  } as Parameters<typeof MessageActions>[0]
  return render(<MessageActions {...props} />)
}

describe("MessageActions Regenerate 可见性矩阵（§17/§19）", () => {
  it("completed 且提供 onRegenerate：显示重新生成", () => {
    renderActions({ completed: true, onRegenerate: noop, messageId: "m1" })
    expect(screen.getByRole("button", { name: "重新生成" })).toBeTruthy()
  })

  it("streaming（completed=false）：隐藏 Like/Dislike/Regenerate", () => {
    renderActions({ completed: false, onRegenerate: noop, messageId: "m1" })
    expect(screen.queryByRole("button", { name: "重新生成" })).toBeNull()
    expect(screen.queryByRole("button", { name: "有帮助" })).toBeNull()
    expect(screen.queryByRole("button", { name: "不满意" })).toBeNull()
    // Copy 仍可用
    expect(screen.getByRole("button", { name: "复制回答" })).toBeTruthy()
  })

  it("completed 但无 onRegenerate（旧版本/非最后一条）：不显示重新生成", () => {
    renderActions({ completed: true, onRegenerate: undefined, messageId: "m1" })
    expect(screen.queryByRole("button", { name: "重新生成" })).toBeNull()
    // Like/Dislike 仍显示
    expect(screen.getByRole("button", { name: "有帮助" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "不满意" })).toBeTruthy()
  })

  it("completed 无 messageId：More 菜单隐藏", () => {
    renderActions({ completed: true, onRegenerate: noop, messageId: undefined })
    expect(screen.queryByRole("button", { name: "更多" })).toBeNull()
  })

  it("completed 有 messageId：More 菜单含「复制消息 ID」", async () => {
    renderActions({ completed: true, onRegenerate: noop, messageId: "stable-msg-1" })
    fireEvent.click(screen.getByRole("button", { name: "更多" }))
    expect(screen.getByText("复制消息 ID")).toBeTruthy()
  })
})
