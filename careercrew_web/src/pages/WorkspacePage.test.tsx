// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

const apiFetchMock = vi.fn()

vi.mock("@/lib/auth", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  getAuthSnapshot: () => ({ status: "authenticated", user: { id: "u-test", username: "test", role: "admin" } }),
}))

import WorkspacePage from "@/pages/WorkspacePage"

const SEARCH_ITEM = {
  message_id: "message-1",
  thread_id: "thread-1",
  turn_id: "turn-1",
  role: "assistant",
  snippet: "建议先把项目经历改写成结果导向，并保留可核验的数据。",
  thread_title: "后端求职准备",
  created_at: "2026-09-10T08:00:00Z",
  score: 1,
}

const REPORT = {
  id: "report-1",
  thread_id: "thread-1",
  source_message_id: "message-1",
  source_answer: "综合意见：优先补齐项目证据。",
  opinions: { planner: "优先补齐项目证据", resume: "突出结果和指标" },
  consensus: [{ point: "项目证据", supporters: ["planner", "resume"] }],
  disagreements: [{ agents: ["planner", "resume"], summary: "侧重点不同" }],
  alternatives: [],
  risks: [{ agent: "system", summary: "执行前需人工核验" }],
  evidence: [],
  status: "draft",
  version: 1,
}

const BOOKMARK = { id: "bookmark-1", message_id: "message-1", snippet: SEARCH_ITEM.snippet, note: "", tags: [] }
const ACTION_ITEM = { id: "action-1", source_message_id: "message-1", source_snippet: SEARCH_ITEM.snippet, title: "补充项目指标", note: "", status: "open" }

function response(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/workspace"]}>
      <WorkspacePage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiFetchMock.mockReset()
  apiFetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.startsWith("/api/workspace/search")) return response({ mode: "text_fallback", query: "项目", total: 1, items: [SEARCH_ITEM] })
    if (url === "/api/workspace/bookmarks") return response([])
    if (url === "/api/workspace/action-items" && (!init?.method || init.method === "GET")) return response([])
    if (url === "/api/workspace/branches") return response([])
    if (url === "/api/workspace/consult-reports") return response([REPORT])
    if (url === "/api/workspace/resumes/masters") return response([])
    if (url === "/api/tools?module=chat") return response({ module: "chat", tools: [
      { id: "rag_query", name: "Knowledge Search", kind: "internal", enabled: true, requires_hitl: false, visible_for_module: true, health: "ready", health_detail: "服务已注册" },
      { id: "mcp_jobs", name: "mcp_jobs", kind: "mcp", enabled: true, requires_hitl: false, visible_for_module: true, health: "restricted", health_detail: "MCP 网络探测仅允许受控服务端路径" },
    ] })
    if (url === "/api/tools/calls") return response([])
    if (url === "/api/workspace/messages/message-1/bookmark" && init?.method === "PUT") return response(BOOKMARK, 200)
    if (url === "/api/workspace/action-items" && init?.method === "POST") return response(ACTION_ITEM, 201)
    if (init?.method === "PUT" || init?.method === "POST" || init?.method === "PATCH" || init?.method === "DELETE") {
      return response({ ...REPORT, ok: true }, init.method === "POST" ? 201 : 200)
    }
    return response([])
  })
})

describe("WorkspacePage", () => {
  it("跨会话搜索支持收藏和创建行动项", async () => {
    renderPage()

    expect(screen.getByRole("heading", { name: "工作台" })).toBeTruthy()
    fireEvent.change(await screen.findByLabelText("跨会话搜索"), { target: { value: "项目" } })
    fireEvent.click(screen.getByRole("button", { name: "搜索" }))

    await waitFor(() => expect(screen.getByText(SEARCH_ITEM.snippet)).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "收藏这条消息" }))
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/workspace/messages/message-1/bookmark",
      expect.objectContaining({ method: "PUT" }),
    ))
    fireEvent.click(screen.getByRole("button", { name: "创建行动项" }))
    fireEvent.change(screen.getByLabelText("行动项标题"), { target: { value: "补充项目指标" } })
    fireEvent.click(screen.getByRole("button", { name: "保存行动项" }))
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/workspace/action-items",
      expect.objectContaining({ method: "POST" }),
    ))
  })

  it("会诊报告展示分歧并支持确认", async () => {
    renderPage()
    fireEvent.click(screen.getByRole("tab", { name: /会诊报告/ }))
    await waitFor(() => expect(screen.getByText("侧重点不同")).toBeTruthy())
    expect(screen.getByText("项目证据（planner、resume）")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "确认报告" }))
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/workspace/consult-reports/report-1",
      expect.objectContaining({ method: "PATCH" }),
    ))
  })

  it("工具中心展示 MCP 受限状态并支持策略更新", async () => {
    renderPage()
    fireEvent.click(screen.getByRole("tab", { name: /工具中心/ }))
    await waitFor(() => expect(screen.getByText("MCP 网络探测仅允许受控服务端路径")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "禁用 Knowledge Search" }))
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/tools/rag_query",
      expect.objectContaining({ method: "PUT" }),
    ))
  })
})
