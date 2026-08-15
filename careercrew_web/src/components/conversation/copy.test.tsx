// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react"
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

  it("点击 Copy → Check → 1.5s 后恢复 Copy", async () => {
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

    // 初始态：Copy 图标
    expect(copyBtn.querySelector(".lucide-copy")).toBeTruthy()
    expect(copyBtn.querySelector(".lucide-check")).toBeNull()

    await act(async () => {
      fireEvent.click(copyBtn)
    })

    // 成功复制后显示 Check（copied=true）
    expect(writeText).toHaveBeenCalledWith("回答")
    expect(copyBtn.querySelector(".lucide-check")).toBeTruthy()
    expect(copyBtn.querySelector(".lucide-copy")).toBeNull()

    // 1.5s 前仍是 Check（copied=true）
    vi.advanceTimersByTime(1400)
    expect(copyBtn.querySelector(".lucide-check")).toBeTruthy()

    act(() => {
      vi.advanceTimersByTime(200) // 累计 > 1500
    })
    // timer 清空后回到 Copy
    expect(copyBtn.querySelector(".lucide-copy")).toBeTruthy()
    expect(copyBtn.querySelector(".lucide-check")).toBeNull()
  })
})
