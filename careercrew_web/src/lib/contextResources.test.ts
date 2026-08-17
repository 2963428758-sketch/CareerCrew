// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  debounce,
  fetchContextResources,
  MENTION_TYPE_LABEL,
  type ContextResource,
} from "@/lib/contextResources"

const apiFetch = vi.hoisted(() => vi.fn())
const apiErrorText = vi.hoisted(() => vi.fn(async () => "后端错误"))
vi.mock("@/lib/auth", () => ({ apiFetch }))
vi.mock("@/lib/errors", () => ({ apiErrorText }))

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as Response
}

const RESOURCES: ContextResource[] = [
  { type: "knowledge_document", id: "doc-1", name: "RAG 技术笔记", visibility: "private" },
  { type: "resume", id: "res-1", name: "李雷的简历.pdf", visibility: "private" },
]

describe("fetchContextResources", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    apiErrorText.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it("无参数时请求 /api/context/resources", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ items: RESOURCES }))
    const rows = await fetchContextResources()
    expect(apiFetch).toHaveBeenCalledWith("/api/context/resources")
    expect(rows).toHaveLength(2)
  })

  it("携带 types 与 q 查询参数", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ items: [] }))
    await fetchContextResources({ types: ["knowledge_document"], q: "RAG" })
    expect(apiFetch).toHaveBeenCalledWith("/api/context/resources?types=knowledge&q=RAG")
  })

  it("items 缺失时返回空数组", async () => {
    apiFetch.mockResolvedValue(jsonResponse({}))
    expect(await fetchContextResources()).toEqual([])
  })

  it("失败时抛出中文错误", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ detail: "x" }, false, 422))
    await expect(fetchContextResources()).rejects.toThrow("后端错误")
  })
})

describe("debounce", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("只在静默期后调用一次", async () => {
    const fn = vi.fn()
    const d = debounce(fn, 100)
    d("a")
    d("b")
    d("c")
    await vi.advanceTimersByTimeAsync(100)
    expect(fn).toHaveBeenCalledOnce()
    expect(fn).toHaveBeenCalledWith("c")
  })
})

describe("MENTION_TYPE_LABEL", () => {
  it("覆盖两种资源类型", () => {
    expect(MENTION_TYPE_LABEL.knowledge_document).toBe("知识文档")
    expect(MENTION_TYPE_LABEL.resume).toBe("简历")
  })
})
