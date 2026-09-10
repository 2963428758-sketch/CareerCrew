// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import PreparationPage from "@/pages/PreparationPage"

const apiFetch = vi.fn()

vi.mock("@/lib/auth", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}))

/** apiFetch 路由式 mock：按 URL 片段与 method 返回。 */
function routeJson(
  handlers: Array<{ match: (url: string, init?: RequestInit) => boolean; payload: unknown; status?: number }>,
) {
  apiFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    for (const h of handlers) {
      if (h.match(url, init)) {
        return { ok: (h.status ?? 200) < 400, status: h.status ?? 200, json: async () => h.payload }
      }
    }
    return { ok: true, status: 200, json: async () => ({}) }
  })
}

const LIST = [
  {
    id: "opp-1", company: "测试公司", title: "Java开发", jd: "负责接口开发",
    city: "深圳", salary: "20-30K", source: "Boss直聘", url: "",
    created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z",
  },
  {
    id: "opp-2", company: "另一家", title: "前端工程师", jd: "负责 Web 前端",
    city: "", salary: "", source: "", url: "",
    created_at: "2026-09-05T00:00:00Z", updated_at: "2026-09-05T00:00:00Z",
  },
]

beforeEach(() => {
  apiFetch.mockReset()
  routeJson([{ match: (url, init2) => url.endsWith("/opportunities") && (init2 === undefined || init2.method === undefined), payload: LIST }])
})

function renderPage(entry = "/preparation") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <PreparationPage />
    </MemoryRouter>,
  )
}

describe("PreparationPage", () => {
  it("加载并渲染岗位列表，点击选择后展示 JD 快照与版本工作台", async () => {
    routeJson([
      { match: (url, init2) => url.endsWith("/opportunities") && (init2 === undefined || init2.method === undefined), payload: LIST },
      { match: (url) => url.includes("/versions") && !url.includes("export"), payload: [] },
    ])
    renderPage()
    await waitFor(() => expect(screen.getByText("测试公司 · Java开发")).toBeTruthy())
    fireEvent.click(screen.getByText("测试公司 · Java开发"))
    await waitFor(() => expect(screen.getByText("JD 快照")).toBeTruthy())
    expect(screen.getAllByText(/负责接口开发/).length).toBeGreaterThan(0)
    expect(screen.getByTestId("resume-workspace")).toBeTruthy()
  })

  it("手动录入：空 JD 阻止保存且不发起请求；填写后保存成功", async () => {
    let created: unknown = null
    apiFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith("/opportunities") && init?.method === "POST") {
        created = JSON.parse(init.body as string)
        return { ok: true, status: 201, json: async () => ({ ...LIST[0], id: "opp-new" }) }
      }
      if (url.endsWith("/opportunities")) {
        return { ok: true, status: 200, json: async () => [] }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    })
    renderPage()
    await waitFor(() => expect(screen.getByText("还没有收藏的岗位")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: /手动录入岗位/ }))
    fireEvent.click(screen.getByRole("button", { name: "保存岗位" }))
    // 必填校验：公司/岗位/JD 为空时不发请求
    expect(created).toBeNull()
    expect(screen.getByText("公司名称不能为空")).toBeTruthy()

    fireEvent.change(screen.getByPlaceholderText("例如：字节跳动"), { target: { value: "测试公司" } })
    fireEvent.change(screen.getByPlaceholderText("例如：大模型应用工程师"), { target: { value: "Java开发" } })
    fireEvent.change(screen.getByPlaceholderText("粘贴完整 JD 文本"), { target: { value: "负责接口开发" } })
    fireEvent.click(screen.getByRole("button", { name: "保存岗位" }))
    await waitFor(() => expect(created).toMatchObject({ company: "测试公司", title: "Java开发" }))
    await waitFor(() => expect(screen.getByText("JD 快照")).toBeTruthy())
  })

  it("保存失败时表单保留输入并显示错误", async () => {
    apiFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith("/opportunities") && init?.method === "POST") {
        return { ok: false, status: 422, json: async () => ({ detail: "JD 长度超出上限" }) }
      }
      if (url.endsWith("/opportunities")) {
        return { ok: true, status: 200, json: async () => [] }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    })
    renderPage()
    fireEvent.click(screen.getByRole("button", { name: /手动录入岗位/ }))
    fireEvent.change(screen.getByPlaceholderText("例如：字节跳动"), { target: { value: "测试公司" } })
    fireEvent.change(screen.getByPlaceholderText("例如：大模型应用工程师"), { target: { value: "Java开发" } })
    fireEvent.change(screen.getByPlaceholderText("粘贴完整 JD 文本"), { target: { value: "负责接口开发" } })
    fireEvent.click(screen.getByRole("button", { name: "保存岗位" }))
    await waitFor(() => expect(screen.getByText("JD 长度超出上限")).toBeTruthy())
    expect((screen.getByPlaceholderText("例如：字节跳动") as HTMLInputElement).value).toBe("测试公司")
  })

  it("删除岗位需要显式确认；确认后从列表移除", async () => {
    apiFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes("/opportunities/opp-1") && init?.method === "DELETE") {
        return { ok: true, status: 200, json: async () => ({ ok: true }) }
      }
      if (url.endsWith("/opportunities")) {
        return { ok: true, status: 200, json: async () => LIST }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    })
    renderPage()
    await waitFor(() => expect(screen.getByText("测试公司 · Java开发")).toBeTruthy())
    // 卡片上的删除按钮（第一个卡片）
    const deleteButtons = screen.getAllByRole("button", { name: "删除" })
    fireEvent.click(deleteButtons[0])
    expect(await screen.findByText(/及其全部简历版本与准备会话将被删除/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "删除岗位" }))
    await waitFor(() => expect(screen.queryByText("测试公司 · Java开发")).toBeNull())
    expect(screen.getByText("另一家 · 前端工程师")).toBeTruthy()
  })

  it("列表加载失败显示错误与重试入口", async () => {
    apiFetch.mockImplementation(async () => {
      throw new TypeError("Failed to fetch")
    })
    renderPage()
    await waitFor(() => expect(screen.getByText(/岗位列表加载失败/)).toBeTruthy())
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy()
  })

  it("URL 带 ?opportunity=<id> 时直接选中该岗位", async () => {
    routeJson([
      { match: (url, init2) => url.endsWith("/opportunities") && (init2 === undefined || init2.method === undefined), payload: LIST },
      { match: (url) => url.includes("/versions"), payload: [] },
    ])
    renderPage("/preparation?opportunity=opp-2")
    await waitFor(() => expect(screen.getByText("JD 快照")).toBeTruthy())
    expect(screen.getAllByText("另一家 · 前端工程师").length).toBeGreaterThan(0)
  })
})
