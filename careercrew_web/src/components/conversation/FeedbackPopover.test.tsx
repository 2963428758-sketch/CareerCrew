// @vitest-environment jsdom
import { createRef } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { FeedbackPopover } from "@/components/conversation/FeedbackPopover"

function rect(top: number, bottom: number, width: number, height: number): DOMRect {
  return { top, bottom, left: 24, right: 24 + width, width, height, x: 24, y: top, toJSON: () => ({}) } as DOMRect
}

describe("FeedbackPopover adaptive placement", () => {
  it("顶部空间不足时翻到回答操作栏下方", async () => {
    const anchorRef = createRef<HTMLDivElement>()
    const original = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.getAttribute("data-testid") === "feedback-anchor") return rect(10, 38, 300, 28)
      if (this.getAttribute("data-testid") === "feedback-popover") return rect(0, 300, 300, 300)
      return rect(0, 0, 0, 0)
    })

    render(
      <div ref={anchorRef} data-testid="feedback-anchor">
        <FeedbackPopover
          open
          anchorRef={anchorRef}
          onClose={vi.fn()}
          onSubmit={vi.fn()}
        />
      </div>,
    )

    await waitFor(() => expect((screen.getByTestId("feedback-popover") as HTMLElement).style.top).toBe("44px"))
    expect(screen.getByTestId("feedback-popover").className).toContain("fixed")
    vi.restoreAllMocks()
    Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", { value: original, configurable: true })
  })

  it("顶部空间充足时仍显示在回答操作栏上方", async () => {
    const anchorRef = createRef<HTMLDivElement>()
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.getAttribute("data-testid") === "feedback-anchor") return rect(500, 528, 300, 28)
      if (this.getAttribute("data-testid") === "feedback-popover") return rect(0, 300, 300, 300)
      return rect(0, 0, 0, 0)
    })

    render(
      <div ref={anchorRef} data-testid="feedback-anchor">
        <FeedbackPopover
          open
          anchorRef={anchorRef}
          onClose={vi.fn()}
          onSubmit={vi.fn()}
        />
      </div>,
    )

    await waitFor(() => expect((screen.getByTestId("feedback-popover") as HTMLElement).style.top).toBe("194px"))
    vi.restoreAllMocks()
  })
})
