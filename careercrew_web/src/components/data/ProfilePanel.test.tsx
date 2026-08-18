// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ProfilePanel } from "@/components/data/ProfilePanel"
import { useChatStore } from "@/store/chatStore"

const apiFetch = vi.hoisted(() => vi.fn())

vi.mock("@/lib/auth", () => ({
  apiFetch,
  getAuthSnapshot: () => ({ user: { id: "u-1" } }),
}))

const profile = {
  user_id: "u-1",
  profile: {
    direction: "后端开发",
    level: "中级",
    experience_years: 3,
    skills: ["Python"],
  },
  preferences: {
    salary_min: 20,
    salary_max: 30,
    city: ["杭州"],
    work_mode: "混合办公",
  },
  target_companies: ["字节跳动"],
}

describe("ProfilePanel save rendering", () => {
  beforeEach(() => {
    apiFetch.mockReset()
    useChatStore.setState({ profileNonce: 0 })
    apiFetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") return { ok: true, status: 200, json: async () => profile }
      return { ok: true, status: 200, json: async () => profile }
    })
  })

  it("自动保存后不重新加载整块画像面板", async () => {
    render(<ProfilePanel />)
    const direction = await screen.findByDisplayValue("后端开发")

    fireEvent.change(direction, { target: { value: "大模型工程" } })
    fireEvent.blur(direction)

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(
        "/api/profile?user_id=u-1",
        expect.objectContaining({ method: "PUT" }),
      )
    })
    const profileGets = apiFetch.mock.calls.filter(([url, init]) =>
      String(url).includes("/api/profile?v=") && !init?.method,
    )
    expect(profileGets).toHaveLength(1)
    expect(screen.getByDisplayValue("大模型工程")).toBeTruthy()
  })
})
