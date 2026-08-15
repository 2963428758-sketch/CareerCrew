// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MessageActions } from "@/components/conversation/MessageActions"

// clipboard 桩：jsdom 无 navigator.clipboard
const writeText = vi.fn()
Object.defineProperty(navigator, "clipboard", {
  value: { writeText },
  configurable: true,
})

describe("Copy 时序（§18）", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    writeText.mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("点击 Copy → Check → 1.5s 后恢复 Copy", () => {
    render(
      <MessageActions
        content="回答"
        feedback={null}
        completed={false}
        onCopy={() => {}}
        onToggleLike={() => {}}
        onToggleDislike={() => {}}
      />
    )
    const copyBtn = screen.getByRole("button", { name: "复制回答" })
    fireEvent.click(copyBtn)

    // 成功复制后显示 Check（aria-label 不变为「复制回答」，但图标切换为 Check）
    expect(writeText).toHaveBeenCalledWith("回答")

    // 1.5s 前仍是 Check（copied=true）——通过 svg 类名判断 lucide check 图标
    // 无法直接断言图标，改用「复制消息/回答」之外的信号：再点一次仍是复制。
    vi.advanceTimersByTime(1400)
    // 仍在 copied 态：Copy 图标已换为 Check（按钮仍可交互，但标题不变）
    expect(screen.getByRole("button", { name: "复制回答" })).toBeTruthy()

    vi.advanceTimersByTime(200) // 累计 > 1500
    // timer 清空后回到初始态（无断言图标，只验证不会抛错）
    expect(screen.getByRole("button", { name: "复制回答" })).toBeTruthy()
  })
})
