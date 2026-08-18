// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { Tooltip } from "@/components/ui/tooltip"

describe("Tooltip", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("pointerdown 时隐藏已经显示的提示气泡", () => {
    render(
      <Tooltip label="拖动调整">
        <button type="button">手柄</button>
      </Tooltip>,
    )

    fireEvent.mouseEnter(screen.getByRole("button", { name: "手柄" }))
    act(() => vi.advanceTimersByTime(160))
    expect(screen.getByRole("tooltip")).toBeTruthy()

    fireEvent.pointerDown(screen.getByRole("button", { name: "手柄" }))

    expect(screen.queryByRole("tooltip")).toBeNull()
  })
})
