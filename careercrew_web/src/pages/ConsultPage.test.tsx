// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, waitFor } from "@testing-library/react"
import ConsultPage from "@/pages/ConsultPage"
import { useThreadStore } from "@/store/threadStore"
import { useStreamStore, IDLE_SESSION } from "@/store/streamStore"

const apiFetch = vi.fn()
vi.mock("@/lib/auth", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

beforeEach(() => {
  apiFetch.mockReset()
  apiFetch.mockImplementation(async () => ({ ok: true, status: 200, json: async () => [] }))
  useThreadStore.setState({ threadsByModule: {}, currentThreadByModule: { consult: "c-a" } })
  useStreamStore.setState({ sessions: {} })
})

describe("ConsultPage 错误占位气泡", () => {
  it("流 error 且无内容时不残留空气泡", async () => {
    useStreamStore.setState({
      sessions: {
        "c-a": { ...IDLE_SESSION, threadId: "c-a", status: "error", errorMsg: "boom" },
      },
    })
    render(<ConsultPage />)
    await waitFor(() => {
      // 历史为空 + 错误状态：不应出现"总调度官结论"空卡片（占位气泡已被移除）
      expect(document.body.textContent || "").not.toContain("总调度官结论")
    })
  })
})
