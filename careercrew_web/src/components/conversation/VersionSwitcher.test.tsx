// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { VersionSwitcher } from "@/components/conversation/VersionSwitcher"

describe("VersionSwitcher（§19.2）", () => {
  it("单版本（total<=1）不渲染", () => {
    const { container } = render(
      <VersionSwitcher index={1} total={1} onPrev={() => {}} onNext={() => {}} />
    )
    expect(container.innerHTML).toBe("")
  })

  it("多版本渲染 `< 1/2 >`，默认最新", () => {
    render(<VersionSwitcher index={2} total={2} onPrev={() => {}} onNext={() => {}} />)
    expect(screen.getByText("2 / 2")).toBeTruthy()
    // 最新版本：next 禁用，prev 可点
    expect(screen.getByRole("button", { name: "下一个版本" }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByRole("button", { name: "上一个版本" }).hasAttribute("disabled")).toBe(false)
  })

  it("最旧版本：prev 禁用", () => {
    render(<VersionSwitcher index={1} total={3} onPrev={() => {}} onNext={() => {}} />)
    expect(screen.getByText("1 / 3")).toBeTruthy()
    expect(screen.getByRole("button", { name: "上一个版本" }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByRole("button", { name: "下一个版本" }).hasAttribute("disabled")).toBe(false)
  })

  it("点击 prev/next 回调发出", () => {
    const onPrev = vi.fn()
    const onNext = vi.fn()
    render(<VersionSwitcher index={2} total={3} onPrev={onPrev} onNext={onNext} />)
    fireEvent.click(screen.getByRole("button", { name: "上一个版本" }))
    fireEvent.click(screen.getByRole("button", { name: "下一个版本" }))
    expect(onPrev).toHaveBeenCalledTimes(1)
    expect(onNext).toHaveBeenCalledTimes(1)
  })
})
