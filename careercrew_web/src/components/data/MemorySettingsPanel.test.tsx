// @vitest-environment jsdom
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { MemorySettingsPanel } from "@/components/data/MemorySettingsPanel"

const apiFetch = vi.hoisted(() => vi.fn())
vi.mock("@/lib/auth", () => ({
  apiFetch,
  getAuthSnapshot: () => ({ user: { id: "u1" } }),
}))

describe("MemorySettingsPanel", () => {
  it("父级关闭时展示生效状态，并禁用子级策略", async () => {
    apiFetch
      .mockResolvedValueOnce(new Response(JSON.stringify({
        enabled: false, feature_enabled: true,
        global: { enabled: false, generate: true, use: true },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        global: { enabled: false, generate: true, use: true },
        user: { user_id: "u1", enabled: true, generate: true, use: true },
        effective: { memory_enabled: false, can_generate: false, can_use: false, can_manual_save: false, can_consolidate: false },
      }), { status: 200 }))

    render(<MemorySettingsPanel />)

    const generate = await screen.findByRole("button", { name: "生成记忆" })
    expect(generate.getAttribute("disabled")).not.toBeNull()
    expect(screen.getByText("全局记忆当前关闭，以下策略暂不生效。")).toBeTruthy()
  })
})
