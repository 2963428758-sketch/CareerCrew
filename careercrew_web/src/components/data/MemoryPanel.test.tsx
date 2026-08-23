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

  it("新记录 UUID 删除时使用 record_id，避免误当作旧条目键", async () => {
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ kind: "fact", id: "550e8400-e29b-41d4-a716-446655440000", type: "profile", ts: "2026-08-23T10:00:00Z" }], next_cursor: null, total: 1,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ deleted: 1 }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ items: [], next_cursor: null, total: 0 }), { status: 200 }))

    render(<MemoryPanel />)
    fireEvent.click(await screen.findByRole("button", { name: "删除记忆 profile" }))
    await waitFor(() => expect(apiFetch.mock.calls.some(
      ([url]) => String(url).includes("record_id=550e8400"),
    )).toBe(true))
  })

  it("服务错误返回 HTML 时给出可操作提示，而非暴露 JSON 解析异常", async () => {
    apiFetch.mockResolvedValueOnce(new Response("<!doctype html><html></html>", {
      status: 200,
      headers: { "Content-Type": "text/html" },
    }))

    render(<MemoryPanel />)

    expect(await screen.findByText(/记忆服务返回了网页，请刷新页面/))
      .toBeTruthy()
  })
})
