// @vitest-environment jsdom
import { render, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"
import App from "@/App"
import { useThreadStore } from "@/store/threadStore"
import { useStreamStore } from "@/store/streamStore"

const apiFetch = vi.fn()

// useSyncExternalStore 要求 getSnapshot 返回缓存引用，否则触发无限重渲染；
// 与 @/lib/auth.ts 中模块级 snapshot 变量的稳定引用语义一致。
const authSnapshot = { status: "authenticated", user: { id: "u_001", username: "liyou", role: "admin" } }

vi.mock("@/lib/auth", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  getAuthSnapshot: () => authSnapshot,
  subscribeAuth: () => () => {},
  restoreSession: () => Promise.resolve(true),
}))

beforeEach(() => {
  apiFetch.mockReset()
  apiFetch.mockImplementation(async () => ({ ok: true, status: 200, json: async () => [] }))
  useStreamStore.setState({ sessions: {} })
  useThreadStore.getState().resetAll()
})

describe("App shell smoke", () => {
  it("renders the authenticated shell with sidebar and workspace without crashing", async () => {
    // 宽视口（≥1100px）：侧边栏展开，对话历史可见
    Object.defineProperty(window, "innerWidth", { value: 1440, configurable: true })
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    )
    // 品牌行 + 模块导航 + 对话历史均应出现在侧边栏
    await waitFor(() => expect(document.body.textContent).toContain("CareerCrew"))
    expect(document.body.textContent).toContain("新对话")
    expect(document.body.textContent).toContain("求职规划")
    expect(document.body.textContent).toContain("对话历史")
  })
})
