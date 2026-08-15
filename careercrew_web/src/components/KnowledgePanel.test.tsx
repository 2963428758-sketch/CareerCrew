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

import KnowledgePanel from "@/components/KnowledgePanel"

const STATUS = {
  points: 4,
  docs: [
    { doc: "mine.pdf", source: "C:\\uploads\\mine_file.pdf", points: 2, category: "knowledge", visibility: "private", owner_user_id: "u_001" },
    { doc: "public.pdf", source: "C:\\uploads\\public_file.pdf", points: 2, category: "knowledge", visibility: "public", owner_user_id: "u_001" },
  ],
}

describe("KnowledgePanel visibility", () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    apiFetchMock.mockResolvedValue({ ok: true, status: 200, json: async () => STATUS })
  })

  it("shows public badge and admin publish controls", async () => {
    render(<KnowledgePanel />)
    await waitFor(() => expect(screen.getByText("mine.pdf")).toBeTruthy())
    expect(screen.getByText("公共")).toBeTruthy()
    expect(screen.getByText("我的")).toBeTruthy()
    // 可见性开关默认「我的私有库」，点击切到「发布到公共库」后断言文案出现
    fireEvent.click(screen.getByText("我的私有库"))
    expect(screen.getByText("发布到公共库")).toBeTruthy()
  })
})
