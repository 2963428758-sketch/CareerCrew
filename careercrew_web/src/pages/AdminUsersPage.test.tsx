// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const apiFetchMock = vi.fn()

// useSyncExternalStore 要求 getSnapshot 返回缓存引用，否则触发无限重渲染；
// 所以这里缓存快照对象（与 @/lib/auth.ts 中模块级 snapshot 变量的稳定引用语义一致）。
const adminSnapshot = {
  status: "authenticated",
  user: { id: "u_001", username: "admin", role: "admin" },
}

vi.mock("@/lib/auth", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  getAuthSnapshot: () => adminSnapshot,
  subscribeAuth: () => () => {},
}))

import AdminUsersPage from "@/pages/AdminUsersPage"

const ACCOUNTS = {
  items: [
    { id: "u_001", username: "admin", role: "admin", status: "active", token_version: 0, created_at: "2026-08-15T00:00:00Z", updated_at: "2026-08-15T00:00:00Z" },
    { id: "u_abc", username: "member", role: "user", status: "active", token_version: 0, created_at: "2026-08-15T01:00:00Z", updated_at: "2026-08-15T01:00:00Z" },
  ],
  total: 2,
  page: 1,
  page_size: 20,
}

describe("AdminUsersPage", () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    apiFetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => ACCOUNTS })
  })

  it("renders account list without password fields", async () => {
    render(<AdminUsersPage />)
    await waitFor(() => expect(screen.getByText("member")).toBeTruthy())
    expect(screen.getByText("admin")).toBeTruthy()
    expect(apiFetchMock).toHaveBeenCalledWith("/api/auth/users?page=1&page_size=100")
    expect(screen.queryByText(/password_hash|token/i)).toBeNull()
  })

  it("creates a user through the form", async () => {
    apiFetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/auth/users" && init?.method === "POST") {
        return Promise.resolve({ ok: true, status: 201, json: async () => ({ id: "u_new", username: "newbie", role: "user", status: "active", token_version: 0, created_at: "", updated_at: "" }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ACCOUNTS })
    })
    render(<AdminUsersPage />)
    await waitFor(() => expect(screen.getByText("member")).toBeTruthy())
    fireEvent.click(screen.getByText("新建用户"))
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "newbie" } })
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "long-password-123" } })
    fireEvent.click(screen.getByText("创建"))
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(([u, i]) => u === "/api/auth/users" && (i as RequestInit)?.method === "POST")
      expect(call).toBeTruthy()
    })
  })
})
