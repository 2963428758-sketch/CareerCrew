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
    // 725e5ee 起 DocRow 展示友好文件名（title/doc_name/源文件名），doc id 仅兜底
    await waitFor(() => expect(screen.getByText("mine_file.pdf")).toBeTruthy())
    expect(screen.getByText("公共")).toBeTruthy()
    expect(screen.getByText("我的")).toBeTruthy()
    // 可见性开关默认「我的私有库」，点击切到「发布到公共库」后断言文案出现
    fireEvent.click(screen.getByText("我的私有库"))
    expect(screen.getByText("发布到公共库")).toBeTruthy()
  })

  it("按需展示知识治理的版本、引用命中，并支持保存元数据和重索引", async () => {
    const documentId = "550e8400-e29b-41d4-a716-446655440010"
    const versionId = "550e8400-e29b-41d4-a716-446655440011"
    apiFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/knowledge") return new Response(JSON.stringify(STATUS), { status: 200 })
      if (url === "/api/knowledge/governance/documents") {
        return new Response(JSON.stringify({
          total: 1,
          items: [{
            id: documentId,
            owner_id: "u_001",
            name: "面试方法论",
            category: "interview",
            visibility: "private",
            status: "active",
            active_version_id: versionId,
            expires_at: null,
            credibility: 0.8,
            citation_hits: 7,
            versions: [{
              id: versionId,
              version_number: 2,
              status: "active",
              expires_at: null,
              credibility: 0.8,
              citation_hits: 7,
              chunks: [{ id: "chunk-1", ordinal: 0, text: "STAR 方法" }],
            }],
          }],
        }), { status: 200 })
      }
      if (url === `/api/knowledge/governance/documents/${documentId}` && init?.method === "PATCH") {
        return new Response(JSON.stringify({ ok: true }), { status: 200 })
      }
      if (url === `/api/knowledge/governance/documents/${documentId}/versions/${versionId}/reindex`) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 })
      }
      throw new Error(`unexpected request: ${url}`)
    })

    render(<KnowledgePanel />)
    await screen.findByText("mine_file.pdf")
    fireEvent.click(screen.getByRole("button", { name: "打开知识治理" }))

    expect(await screen.findByText("面试方法论")).toBeTruthy()
    expect(screen.getByText(/1 个版本/)).toBeTruthy()
    expect(screen.getAllByText(/引用命中 7/).length).toBe(2)

    fireEvent.change(screen.getByRole("spinbutton", { name: "可信度 面试方法论" }), { target: { value: "0.6" } })
    fireEvent.change(screen.getByLabelText("失效日期 面试方法论"), { target: { value: "2027-01-15" } })
    fireEvent.click(screen.getByRole("button", { name: "保存治理设置 面试方法论" }))
    await waitFor(() => expect(apiFetchMock.mock.calls.some(([url, request]) =>
      url === `/api/knowledge/governance/documents/${documentId}`
      && (request as RequestInit).method === "PATCH"
      && JSON.parse(String((request as RequestInit).body)).credibility === 0.6
      && JSON.parse(String((request as RequestInit).body)).expires_at === "2027-01-15",
    )).toBe(true))

    fireEvent.click(screen.getByRole("button", { name: "重新索引 v2" }))
    await waitFor(() => expect(apiFetchMock.mock.calls.some(([url, request]) =>
      url === `/api/knowledge/governance/documents/${documentId}/versions/${versionId}/reindex`
      && (request as RequestInit | undefined)?.method === "POST",
    )).toBe(true))
  })

  it("治理接口不可用时保留传统知识库列表并显示可操作错误", async () => {
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/knowledge") return new Response(JSON.stringify(STATUS), { status: 200 })
      if (url === "/api/knowledge/governance/documents") return new Response("治理服务不可用", { status: 503 })
      throw new Error(`unexpected request: ${url}`)
    })

    render(<KnowledgePanel />)
    await screen.findByText("mine_file.pdf")
    fireEvent.click(screen.getByRole("button", { name: "打开知识治理" }))

    expect(await screen.findByText(/知识治理加载失败/)).toBeTruthy()
    expect(screen.getByText("public_file.pdf")).toBeTruthy()
  })

  it("重新索引过程中显示状态，失败后保留错误提示", async () => {
    const documentId = "550e8400-e29b-41d4-a716-446655440020"
    const versionId = "550e8400-e29b-41d4-a716-446655440021"
    let releaseReindex!: (response: Response) => void
    const reindexResponse = new Promise<Response>((resolve) => { releaseReindex = resolve })
    apiFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/knowledge") return new Response(JSON.stringify(STATUS), { status: 200 })
      if (url === "/api/knowledge/governance/documents") {
        return new Response(JSON.stringify({ items: [{
          id: documentId, name: "知识文档", status: "active", visibility: "private", credibility: 1,
          citation_hits: 0, versions: [{ id: versionId, version_number: 1, status: "active", chunks: [] }],
        }], total: 1 }), { status: 200 })
      }
      if (url.endsWith(`/versions/${versionId}/reindex`) && init?.method === "POST") return reindexResponse
      throw new Error(`unexpected request: ${url}`)
    })

    render(<KnowledgePanel />)
    await screen.findByText("mine_file.pdf")
    fireEvent.click(screen.getByRole("button", { name: "打开知识治理" }))
    await screen.findByText("知识文档")
    fireEvent.click(screen.getByRole("button", { name: "重新索引 v1" }))

    expect(await screen.findByText("索引中…")).toBeTruthy()
    releaseReindex(new Response(JSON.stringify({ detail: "重新索引失败" }), { status: 503 }))
    expect(await screen.findByText(/知识治理加载失败：重新索引失败/)).toBeTruthy()
  })
})
