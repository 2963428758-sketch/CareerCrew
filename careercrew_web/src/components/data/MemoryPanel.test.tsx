// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { MemoryPanel } from "@/components/data/MemoryPanel"

const apiFetch = vi.hoisted(() => vi.fn())
vi.mock("@/lib/auth", () => ({ apiFetch }))

describe("MemoryPanel", () => {
  it("按事实和关键事件分组，且通过游标继续加载", async () => {
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [
        { kind: "fact", id: "profile.direction", type: "profile", ts: "2026-08-23T10:00:00Z", content: { direction: "AI Engineer" } },
        { kind: "event", id: "offer-1", type: "offer", ts: "2026-08-22T10:00:00Z", content: { company: "OpenAI" } },
      ], next_cursor: "next-page", total: 3,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ kind: "event", id: "event-2", type: "application", ts: "2026-08-21T10:00:00Z", content: { company: "Anthropic" } }],
      next_cursor: null, total: 3,
    }), { status: 200 }))

    render(<MemoryPanel />)

    expect(await screen.findByRole("heading", { name: "当前事实" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "关键事件" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "加载更多记忆" }))
    await waitFor(() => expect(screen.getByText("Anthropic")).toBeTruthy())
  })
})
