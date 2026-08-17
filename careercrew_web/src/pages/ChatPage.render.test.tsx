// @vitest-environment jsdom
import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { useThreadStore } from "@/store/threadStore"
import { useStreamStore } from "@/store/streamStore"

vi.mock("@/lib/auth", () => ({
  apiFetch: () => new Promise(() => {}),
  getAuthSnapshot: () => ({ status: "authenticated", user: { id: "u_001", username: "liyou", role: "admin" } }),
  subscribeAuth: () => () => {},
}))

import ChatPage from "@/pages/ChatPage"

describe("ChatPage render stability", () => {
  it("renders the Codex-style shell without render loop", () => {
    useThreadStore.setState({ currentThreadByModule: { chat: "t-a" } })
    useStreamStore.setState({ sessions: {} })
    expect(() => render(<ChatPage />)).not.toThrow()
  })
})
