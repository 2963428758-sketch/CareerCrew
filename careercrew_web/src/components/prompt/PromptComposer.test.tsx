// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { PromptComposer } from "@/components/prompt/PromptComposer"

describe("PromptComposer", () => {
  it("工具栏只保留添加附件入口", () => {
    const onAddAttachment = vi.fn()
    render(
      <PromptComposer
        value=""
        onChange={vi.fn()}
        onSend={vi.fn()}
        toolbar
        onAddAttachment={onAddAttachment}
      />,
    )

    fireEvent.click(screen.getByRole("button", { name: "添加附件" }))

    expect(onAddAttachment).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("button", { name: "提及资料" })).toBeNull()
    expect(screen.queryByRole("button", { name: /工具/ })).toBeNull()
  })
})
