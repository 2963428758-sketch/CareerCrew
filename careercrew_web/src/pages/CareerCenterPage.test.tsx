// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import CareerCenterPage from "@/pages/CareerCenterPage"

const apiFetch = vi.fn()

vi.mock("@/lib/auth", () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}))

beforeEach(() => {
  apiFetch.mockReset()
  apiFetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith("/board")) return { ok: true, status: 200, json: async () => [] }
    if (url.endsWith("/stats")) {
      return {
        ok: true, status: 200, json: async () => ({
          by_stage: { 待准备: 2, 已投递: 1 },
          by_source: { 内推: { total: 2, by_stage: { 已投递: 1 } } },
          by_version: { 归因版本: { total: 1, by_stage: { 已投递: 1 } } },
          applied: 1, replies: 0, interviewed: 0, offers: 0,
          reply_rate: { numerator: 0, denominator: 1, rate: 0 },
          interview_rate: { numerator: 0, denominator: 1, rate: 0 },
          offer_rate: { numerator: 0, denominator: 0, rate: null },
          tasks: { open: 2, done: 1 },
        }),
      }
    }
    return { ok: true, status: 200, json: async () => [] }
  })
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/career"]}>
      <CareerCenterPage />
    </MemoryRouter>,
  )
}

describe("CareerCenterPage", () => {
  it("渲染八个 tab 与空看板空态", async () => {
    renderPage()
    expect(screen.getByText("求职中心")).toBeTruthy()
    for (const label of ["进度看板", "行动计划", "素材库", "HR 跟进", "Offer 对比", "面试复盘", "效果统计", "数据与隐私"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeTruthy()
    }
    await waitFor(() => expect(screen.getByText("看板还是空的")).toBeTruthy())
  })

  it("效果统计展示转化率与样本量（分母为 0 显示样本不足）", async () => {
    renderPage()
    fireEvent.click(screen.getByRole("button", { name: /效果统计/ }))
    await waitFor(() => expect(screen.getByText(/转化率/)).toBeTruthy())
    expect(screen.getByText(/样本不足/)).toBeTruthy()
    expect(screen.getAllByText(/已投递/).length).toBeGreaterThan(0)
  })

  it("行动计划：创建任务需要标题；空标题不发请求", async () => {
    renderPage()
    fireEvent.click(screen.getByRole("button", { name: /行动计划/ }))
    await waitFor(() => expect(screen.getByText("没有任务")).toBeTruthy())
    const calls = apiFetch.mock.calls.length
    fireEvent.click(screen.getByRole("button", { name: /添加/ }))
    expect(apiFetch.mock.calls.length).toBe(calls)
  })
})
