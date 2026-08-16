// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ToolPicker } from "@/components/prompt/ToolPicker"
import type { ToolCapability } from "@/lib/agentCapabilities"

// ---- 依赖桩：lib 层 mock，隔离组件行为 ----
const fetchAgentCapabilities = vi.hoisted(() => vi.fn())
vi.mock("@/lib/agentCapabilities", () => {
  const toolDisplayName = (c: { id: string; name: string }) =>
    c.name && c.name !== c.id ? c.name : c.id
  const resolveSelectedToolIds = (_caps: unknown[], selected: string[]) => selected
  return { fetchAgentCapabilities, toolDisplayName, resolveSelectedToolIds }
})

function cap(overrides: Partial<ToolCapability> = {}): ToolCapability {
  return {
    id: "rag_query",
    name: "Knowledge Search",
    enabled: true,
    requires_hitl: false,
    ...overrides,
  }
}

describe("ToolPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchAgentCapabilities.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it("打开后拉取能力并展示选项", async () => {
    fetchAgentCapabilities.mockResolvedValue([cap(), cap({ id: "submit_application", name: "Submit Application", requires_hitl: true })])
    render(<ToolPicker />)

    fireEvent.click(screen.getByRole("button", { name: "工具" }))
    const opts = await screen.findAllByTestId("tool-option")
    expect(opts).toHaveLength(2)
    expect(opts[0].textContent).toContain("Knowledge Search")
    expect(opts[1].textContent).toContain("Submit Application")
  })

  it("勾选 → chip + onToolsChange；取消 → 移除", async () => {
    fetchAgentCapabilities.mockResolvedValue([cap()])
    const onChange = vi.fn()
    render(<ToolPicker onToolsChange={onChange} />)

    fireEvent.click(screen.getByRole("button", { name: "工具" }))
    fireEvent.click(await screen.findByTestId("tool-option"))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(["rag_query"]))
    expect(screen.getByTestId("tool-chip").textContent).toContain("Knowledge Search")

    // 取消选中
    fireEvent.click(screen.getByTestId("tool-option"))
    await waitFor(() => {
      expect(onChange).toHaveBeenLastCalledWith([])
      expect(screen.queryByTestId("tool-chip")).toBeNull()
    })
  })

  it("disabled 工具不可勾选", async () => {
    fetchAgentCapabilities.mockResolvedValue([cap({ id: "profile_update", enabled: false })])
    const onChange = vi.fn()
    render(<ToolPicker onToolsChange={onChange} />)

    fireEvent.click(screen.getByRole("button", { name: "工具" }))
    const opt = await screen.findByTestId("tool-option")
    expect((opt as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(opt)
    expect(onChange).not.toHaveBeenCalled()
  })

  it("加载失败展示错误并可重试", async () => {
    fetchAgentCapabilities.mockRejectedValueOnce(new Error("加载工具能力失败"))
      .mockResolvedValueOnce([cap()])
    render(<ToolPicker />)

    fireEvent.click(screen.getByRole("button", { name: "工具" }))
    expect(await screen.findByText(/加载工具能力失败/)).toBeDefined()

    fireEvent.click(screen.getByText(/重试/))
    await screen.findByTestId("tool-option")
  })
})
