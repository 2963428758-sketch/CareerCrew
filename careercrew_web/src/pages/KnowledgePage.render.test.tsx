// @vitest-environment jsdom
import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

// 回归：登录后首次进入知识库页（线程列表尚未加载）时，selector 不得返回新数组，
// 否则 zustand v5 + React 19 触发 useSyncExternalStore 无限循环（白屏）。
vi.mock("@/lib/auth", () => ({
  apiFetch: () => new Promise(() => {}),
  getAuthSnapshot: () => ({ status: "authenticated", user: { id: "u_001", username: "liyou", role: "admin" } }),
  subscribeAuth: () => () => {},
}))

import KnowledgePage from "@/pages/KnowledgePage"

describe("KnowledgePage render stability", () => {
  it("renders with empty thread store without render loop", () => {
    expect(() => render(<KnowledgePage />)).not.toThrow()
  })
})
