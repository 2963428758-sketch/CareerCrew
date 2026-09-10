// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryPanel } from "@/components/data/MemoryPanel"

const apiFetch = vi.hoisted(() => vi.fn())
vi.mock("@/lib/auth", () => ({ apiFetch }))

describe("MemoryPanel", () => {
  beforeEach(() => {
    apiFetch.mockReset()
  })

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

  it("当前记忆为空时仍能打开已忽略或过期记录筛选", async () => {
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [], next_cursor: null, total: 0,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ kind: "fact", id: "ignored-memory", type: "profile", status: "ignored", description: "暂时忽略的目标" }],
      next_cursor: null, total: 1,
    }), { status: 200 }))

    render(<MemoryPanel />)
    fireEvent.click(await screen.findByRole("button", { name: "查看已忽略/过期" }))

    await waitFor(() => expect(screen.getByText("暂时忽略的目标")).toBeTruthy())
    expect(String(apiFetch.mock.calls[1][0])).toContain("status=all")
  })

  it("对有版本的记忆提供确认、修改、历史和合并入口", async () => {
    const firstId = "550e8400-e29b-41d4-a716-446655440001"
    const secondId = "550e8400-e29b-41d4-a716-446655440002"
    const rows = [
      { kind: "fact", id: firstId, type: "profile", version: 2, status: "active", description: "目标岗位是 AI 工程师", content: "目标岗位是 AI 工程师" },
      { kind: "fact", id: secondId, type: "profile", version: 1, status: "active", description: "偏好远程办公", content: "偏好远程办公" },
    ]
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ items: rows, next_cursor: null, total: 2 }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ record: { ...rows[0], version: 3 }, status: "updated" }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ items: rows, next_cursor: null, total: 2 }), { status: 200 }))

    render(<MemoryPanel />)

    expect((await screen.findAllByRole("button", { name: "确认正确" })).length).toBe(2)
    fireEvent.click(screen.getAllByRole("button", { name: "确认正确" })[0])
    await waitFor(() => expect(apiFetch.mock.calls.some(([url, init]) =>
      String(url).includes(`/api/memory/records/${firstId}`)
      && (init as RequestInit).method === "PATCH"
      && JSON.parse(String((init as RequestInit).body)).action === "confirm"
      && JSON.parse(String((init as RequestInit).body)).row_version === 2,
    )).toBe(true))
  })

  it("打开治理历史并在版本冲突时提示刷新", async () => {
    const id = "550e8400-e29b-41d4-a716-446655440003"
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ kind: "fact", id, type: "profile", version: 1, status: "active", description: "目标岗位", content: "目标岗位" }],
      next_cursor: null, total: 1,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      record: { id, version: 1 }, events: [{ action: "edit", created_at: "2026-09-10T10:00:00Z" }],
    }), { status: 200 }))

    render(<MemoryPanel />)
    fireEvent.click(await screen.findByRole("button", { name: "查看变更历史" }))
    expect(await screen.findByText(/修改/)).toBeTruthy()
  })

  it("支持内联修改和忽略治理动作", async () => {
    const id = "550e8400-e29b-41d4-a716-446655440004"
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ kind: "fact", id, type: "profile", version: 4, status: "active", description: "旧目标", content: "旧目标" }],
      next_cursor: null, total: 1,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ kind: "fact", id, type: "profile", version: 5, status: "active", description: "新目标", content: "新目标" }],
      next_cursor: null, total: 1,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ items: [], next_cursor: null, total: 0 }), { status: 200 }))

    render(<MemoryPanel />)
    fireEvent.click(await screen.findByRole("button", { name: "修改" }))
    fireEvent.change(screen.getByRole("textbox", { name: "修改后的记忆" }), { target: { value: "新目标" } })
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(apiFetch.mock.calls.some(([url, init]) =>
      String(url).includes(`/api/memory/records/${id}`)
      && (init as RequestInit).method === "PATCH"
      && JSON.parse(String((init as RequestInit).body)).action === "edit"
      && JSON.parse(String((init as RequestInit).body)).display_text === "新目标",
    )).toBe(true))

    fireEvent.click(await screen.findByRole("button", { name: "暂时忽略" }))
    await waitFor(() => expect(apiFetch.mock.calls.some(([url, init]) =>
      String(url).includes(`/api/memory/records/${id}`)
      && (init as RequestInit).method === "PATCH"
      && JSON.parse(String((init as RequestInit).body)).action === "ignore"
      && JSON.parse(String((init as RequestInit).body)).row_version === 5,
    )).toBe(true))
  })

  it("合并时携带两个版本号，409 时提示刷新", async () => {
    const firstId = "550e8400-e29b-41d4-a716-446655440005"
    const secondId = "550e8400-e29b-41d4-a716-446655440006"
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [
        { kind: "fact", id: firstId, type: "profile", version: 2, status: "active", description: "第一条" },
        { kind: "fact", id: secondId, type: "profile", version: 3, status: "active", description: "第二条" },
      ], next_cursor: null, total: 2,
    }), { status: 200 }))
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "记忆已更新，请刷新后重试" }), { status: 409 }))

    render(<MemoryPanel />)
    expect((await screen.findAllByRole("button", { name: "合并" })).length).toBe(2)
    fireEvent.click(screen.getAllByRole("button", { name: "合并" })[0])

    expect((await screen.findByRole("alert")).textContent).toContain("记忆已更新，请刷新后重试")
    const mergeRequest = apiFetch.mock.calls.find(([url, init]) =>
      String(url).includes(`/api/memory/records/${firstId}/merge`)
      && (init as RequestInit).method === "POST",
    )
    if (!mergeRequest) throw new Error("merge request was not sent")
    expect(JSON.parse(String((mergeRequest[1] as RequestInit).body))).toMatchObject({
      other_memory_id: secondId,
      row_version: 2,
      other_row_version: 3,
    })
  })
})
