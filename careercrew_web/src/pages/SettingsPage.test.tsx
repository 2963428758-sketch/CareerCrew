// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ChangePasswordCard } from "@/pages/SettingsPage"

const apiFetch = vi.hoisted(() => vi.fn())
vi.mock("@/lib/auth", () => ({
  apiFetch,
  logout: vi.fn(),
  getAuthSnapshot: () => ({ user: null }),
  subscribeAuth: () => () => {},
}))

describe("ChangePasswordCard", () => {
  it("新密码失焦且不符合策略时显示输入框旁的气泡提示", () => {
    apiFetch.mockReset()
    render(<ChangePasswordCard />)

    fireEvent.change(screen.getByPlaceholderText("请输入当前密码"), { target: { value: "old-password" } })
    const newPassword = screen.getByPlaceholderText("8-64 位，包含字母和数字")
    fireEvent.change(newPassword, { target: { value: "abc" } })
    fireEvent.blur(newPassword)

    expect(screen.getByRole("alert").textContent).toContain("8-64 位")
    expect(newPassword.getAttribute("aria-invalid")).toBe("true")
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it("新密码为空时失焦不显示策略气泡", () => {
    render(<ChangePasswordCard />)
    const newPassword = screen.getByPlaceholderText("8-64 位，包含字母和数字")

    fireEvent.blur(newPassword)

    expect(screen.queryByRole("alert")).toBeNull()
    expect(newPassword.getAttribute("aria-invalid")).toBeNull()
  })
})
