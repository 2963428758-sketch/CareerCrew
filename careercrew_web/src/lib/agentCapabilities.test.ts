// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  fetchAgentCapabilities,
  resolveSelectedToolIds,
  toolDisplayName,
  type ToolCapability,
} from "@/lib/agentCapabilities"

const apiFetch = vi.hoisted(() => vi.fn())
const apiErrorText = vi.hoisted(() => vi.fn(async () => "后端错误"))
vi.mock("@/lib/auth", () => ({ apiFetch }))
vi.mock("@/lib/errors", () => ({ apiErrorText }))

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as Response
}

function cap(overrides: Partial<ToolCapability> = {}): ToolCapability {
  return { id: "rag_query", name: "Knowledge Search", enabled: true, requires_hitl: false, ...overrides }
}

describe("fetchAgentCapabilities", () => {
  beforeEach(() => apiFetch.mockReset())
  afterEach(() => vi.restoreAllMocks())

  it("拼接 module 并解析 tools", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ tools: [cap()] }))
    const rows = await fetchAgentCapabilities("chat")
    expect(apiFetch).toHaveBeenCalledWith("/api/agent/capabilities?module=chat")
    expect(rows).toEqual([cap()])
  })

  it("缺省参数默认 module=chat", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ tools: [] }))
    await fetchAgentCapabilities()
    expect(apiFetch).toHaveBeenCalledWith("/api/agent/capabilities?module=chat")
  })

  it("非 ok 响应抛中文化错误", async () => {
    apiFetch.mockResolvedValue(jsonResponse({ detail: "服务不可用" }, false, 503))
    await expect(fetchAgentCapabilities("chat")).rejects.toThrow("后端错误")
  })
})

describe("resolveSelectedToolIds", () => {
  it("裁剪 enabled=false 与不在 capability 列表的 id 并保序去重", () => {
    const caps = [
      cap({ id: "rag_query" }),
      cap({ id: "profile_update", enabled: false }),
      cap({ id: "memory_search" }),
    ]
    const out = resolveSelectedToolIds(caps, ["rag_query", "evil", "rag_query", "memory_search", "profile_update"])
    expect(out).toEqual(["rag_query", "memory_search"])
  })
})

describe("toolDisplayName", () => {
  it("后端 name 优先", () => {
    expect(toolDisplayName(cap({ name: "Knowledge Search" }))).toBe("Knowledge Search")
  })
  it("name 为 id 时回退本地映射", () => {
    expect(toolDisplayName(cap({ id: "memory_search", name: "memory_search" }))).toBe("Memory Search")
  })
  it("无映射回退 id", () => {
    expect(toolDisplayName(cap({ id: "custom", name: "custom" }))).toBe("custom")
  })
})
