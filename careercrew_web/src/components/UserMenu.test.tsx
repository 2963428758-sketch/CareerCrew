// @vitest-environment jsdom
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { UserMenu } from "@/components/UserMenu"

const authSnapshot = {
  status: "authenticated",
  user: { id: "u_001", username: "liyou", display_name: "李优", role: "admin" },
}

vi.mock("@/lib/auth", () => ({
  getAuthSnapshot: () => authSnapshot,
  subscribeAuth: () => () => {},
  logout: vi.fn(),
}))

vi.mock("@/lib/avatar", () => ({
  useAvatar: () => null,
}))

describe("UserMenu collapsed layout", () => {
  it("places the role indicator beside the avatar instead of over it", () => {
    render(
      <MemoryRouter>
        <UserMenu collapsed />
      </MemoryRouter>,
    )

    const group = screen.getByTestId("collapsed-user-avatar-group")
    const indicator = screen.getByTestId("collapsed-user-role-indicator")

    expect(group.className).toContain("w-8")
    expect(indicator.className).toContain("right-0")
    expect(indicator.className).toContain("h-2")
    expect(indicator.className).not.toContain("right-[9px]")
  })

  it("does not render the compact role indicator when expanded", () => {
    render(
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>,
    )

    expect(screen.queryByTestId("collapsed-user-role-indicator")).toBeNull()
  })
})
